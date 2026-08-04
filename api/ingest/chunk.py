"""Stage 3 — sections to retrievable chunks, with the strategy as a swappable argument.

    .venv/Scripts/python -m ingest.chunk --strategy heading
    .venv/Scripts/python -m ingest.chunk --strategy section
    .venv/Scripts/python -m ingest.chunk --strategy fixed
    .venv/Scripts/python -m ingest.chunk --compare      # run all, print a comparison table

Reads data/sections/*.json, writes data/chunks/<strategy>.json. Because the earlier stages
persisted their output, changing strategy re-runs only this stage and the embedding —
nobody's server gets touched again. That is the whole reason the pipeline is staged, and
it is what makes an ablation cheap enough to actually run.

**Every chunk records which source sections it covers.** This matters more than it looks:
an ablation changes chunk boundaries by definition, so eval labels that point at chunk ids
would break on every run. Labelling by source section and scoring a hit when a retrieved
chunk *covers* that section keeps one set of labels valid across all strategies. Getting
this wrong is the standard way ablations end up unfalsifiable.

Section keys are `slug#heading_path`, and the slug is not optional: "Academic Policies >
Grading" occurs on seven different schools' pages. That collision is the near-duplicate
property that makes this corpus worth retrieving over — and it is exactly what would have
made an unqualified heading label ambiguous. (One genuine duplicate survives: the SPS
graduate page repeats the heading "Residency Requirements > Master's Programs" for two
related rules. A label there matches both, which is semantically fine.)

Parameters below come from the measured distribution in stage 2 (median 622 chars, p75
1062, p95 2464, max 11839; 15% under 200, 3% over 3000), not from a blog post.
"""

import argparse
import json
import re
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SECTIONS_DIR = DATA_DIR / "sections"
CHUNKS_DIR = DATA_DIR / "chunks"

# A section below this is too small to stand alone as a retrieval unit — it retrieves on
# stray keywords and carries no context. 15% of sections are in this range.
MIN_CHARS = 200
# Comfortable upper bound for a coherent chunk; roughly 300 tokens.
TARGET_CHARS = 1200
# Above this a chunk starts spanning unrelated rules, so it gets split. 3% of sections.
MAX_CHARS = 3000
# Fixed-window baseline settings.
FIXED_WINDOW = 1200
FIXED_OVERLAP = 150


@dataclass
class Chunk:
    chunk_key: str
    slug: str
    url: str
    page_title: str
    school: str
    level: str
    topic: str
    office: str
    scope: str
    heading_path: str
    # Every source section this chunk covers, as `slug#heading_path`. Eval labels
    # reference these rather than chunk ids, so labels survive a change of strategy.
    section_keys: list[str]
    anchor: str | None
    text: str
    char_count: int = 0
    strategy: str = ""
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.char_count = len(self.text)


def _common_path(paths: list[str]) -> str:
    """Deepest heading path shared by several sections — the merged chunk's address."""
    if not paths:
        return ""
    split = [p.split(" > ") for p in paths]
    shared: list[str] = []
    for parts in zip(*split):
        if len(set(parts)) == 1:
            shared.append(parts[0])
        else:
            break
    return " > ".join(shared) if shared else split[0][0]


def _split_long(text: str, target: int, hard_max: int) -> list[str]:
    """Split oversized text at paragraph boundaries, falling back to sentences."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    pieces: list[str] = []
    buffer = ""

    def flush() -> None:
        nonlocal buffer
        if buffer.strip():
            pieces.append(buffer.strip())
        buffer = ""

    for para in paragraphs:
        if len(para) > hard_max:
            flush()
            # A single paragraph over the hard max: break on sentence ends.
            sentences = re.split(r"(?<=[.!?])\s+", para)
            for sentence in sentences:
                if len(buffer) + len(sentence) + 1 > target and buffer:
                    flush()
                buffer = f"{buffer} {sentence}".strip()
            flush()
            continue
        if len(buffer) + len(para) + 2 > target and buffer:
            flush()
        buffer = f"{buffer}\n\n{para}".strip()
    flush()
    return pieces or [text.strip()]


def _make(
    page: dict, heading_path: str, headings: list[str], anchor: str | None,
    text: str, index: int, strategy: str, extra: dict | None = None,
) -> Chunk:
    return Chunk(
        chunk_key=f"{page['slug']}#{index:03d}",
        slug=page["slug"],
        url=page["url"],
        page_title=page["title"],
        school=page["school"],
        level=page["level"],
        topic=page["topic"],
        office=page["office"],
        scope=page["scope"],
        heading_path=heading_path,
        section_keys=[f"{page['slug']}#{h}" for h in headings],
        anchor=anchor,
        text=text,
        strategy=strategy,
        extra=extra or {},
    )


# --------------------------------------------------------------------------------------
# Strategies
# --------------------------------------------------------------------------------------


def strategy_section(page: dict) -> list[Chunk]:
    """One chunk per extracted section. The naive structural baseline: no merging, no
    splitting, so it inherits the raw size distribution including the 25-char stubs."""
    return [
        _make(page, s["heading_path"], [s["heading_path"]], s["anchor"], s["text"], i, "section")
        for i, s in enumerate(page["sections"])
    ]


def strategy_fixed(page: dict) -> list[Chunk]:
    """Fixed windows with overlap, structure discarded.

    The honest baseline. Headings are inlined as they would render on the page, then the
    whole document is windowed on character count — so rules get cut mid-sentence and a
    chunk's ancestry is lost. Included precisely so the ablation can show what structural
    chunking buys rather than asserting it.
    """
    document_parts: list[str] = []
    for s in page["sections"]:
        document_parts.append(s["heading"])
        document_parts.append(s["text"])
    document = "\n\n".join(document_parts)

    chunks: list[Chunk] = []
    start = 0
    index = 0
    while start < len(document):
        end = min(start + FIXED_WINDOW, len(document))
        text = document[start:end].strip()
        if text:
            chunks.append(
                _make(
                    page, page["title"], [], None, text, index, "fixed",
                    {"window": [start, end]},
                )
            )
            index += 1
        if end >= len(document):
            break
        start = end - FIXED_OVERLAP
    return chunks


def strategy_heading(page: dict) -> list[Chunk]:
    """Structure-aware: merge undersized siblings, split oversized sections.

    Merging keeps each source section's own heading inline in the text, so combining three
    short notices does not erase which notice is which. Course-catalog pages are left
    alone — a course is already the unit a question is about.
    """
    sections = page["sections"]
    if not sections:
        return []

    # Course pages: one course per chunk, never merged or split.
    if page["topic"] == "courses":
        return [
            _make(page, s["heading_path"], [s["heading_path"]], s["anchor"], s["text"], i,
                  "heading", {"atomic": "course"})
            for i, s in enumerate(sections)
        ]

    chunks: list[Chunk] = []
    index = 0
    buffer: list[dict] = []

    def parent_of(section: dict) -> str:
        parts = section["heading_path"].split(" > ")
        return " > ".join(parts[:-1]) if len(parts) > 1 else parts[0]

    def flush_buffer() -> None:
        nonlocal index, buffer
        if not buffer:
            return
        if len(buffer) == 1:
            s = buffer[0]
            text, headings, anchor = s["text"], [s["heading_path"]], s["anchor"]
            path = s["heading_path"]
        else:
            # Keep each merged section's heading inline so the distinction survives.
            text = "\n\n".join(f"{s['heading']}\n{s['text']}" for s in buffer)
            headings = [s["heading_path"] for s in buffer]
            anchor = buffer[0]["anchor"]
            path = _common_path(headings)

        for piece in _split_long(text, TARGET_CHARS, MAX_CHARS) if len(text) > MAX_CHARS else [text]:
            chunks.append(
                _make(page, path, headings, anchor, piece, index, "heading",
                      {"merged": len(buffer)} if len(buffer) > 1 else {})
            )
            index += 1
        buffer = []

    for section in sections:
        if buffer and parent_of(section) != parent_of(buffer[-1]):
            # Different parent: never merge across a topic boundary.
            flush_buffer()

        buffer.append(section)
        current_len = sum(len(s["text"]) for s in buffer)
        if current_len >= MIN_CHARS:
            flush_buffer()

    flush_buffer()
    return chunks


STRATEGIES = {
    "heading": strategy_heading,
    "section": strategy_section,
    "fixed": strategy_fixed,
}


# --------------------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------------------


def load_pages() -> list[dict]:
    pages = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(SECTIONS_DIR.glob("*.json"))]
    if not pages:
        raise SystemExit("No sections found. Run `python -m ingest.extract` first.")
    return pages


def build(strategy: str, pages: list[dict]) -> list[Chunk]:
    fn = STRATEGIES[strategy]
    chunks: list[Chunk] = []
    for page in pages:
        chunks.extend(fn(page))
    return chunks


def describe(strategy: str, chunks: list[Chunk]) -> dict:
    sizes = sorted(c.char_count for c in chunks)
    covered = {k for c in chunks for k in c.section_keys}
    return {
        "strategy": strategy,
        "chunks": len(chunks),
        "median_chars": int(statistics.median(sizes)) if sizes else 0,
        "p95_chars": sizes[int(len(sizes) * 0.95)] if sizes else 0,
        "max_chars": sizes[-1] if sizes else 0,
        "under_200": sum(1 for s in sizes if s < 200),
        "over_3000": sum(1 for s in sizes if s > 3000),
        "sections_covered": len(covered),
        "total_chars": sum(sizes),
    }


def write(strategy: str, chunks: list[Chunk]) -> Path:
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    path = CHUNKS_DIR / f"{strategy}.json"
    path.write_text(
        json.dumps(
            {"strategy": strategy, "stats": describe(strategy, chunks),
             "chunks": [asdict(c) for c in chunks]},
            indent=2, ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=sorted(STRATEGIES), default="heading")
    parser.add_argument("--compare", action="store_true", help="build all strategies and compare")
    args = parser.parse_args()

    pages = load_pages()
    total_sections = sum(len(p["sections"]) for p in pages)
    print(f"pages: {len(pages)}   sections: {total_sections}")

    targets = sorted(STRATEGIES) if args.compare else [args.strategy]
    rows = []
    for strategy in targets:
        chunks = build(strategy, pages)
        path = write(strategy, chunks)
        stats = describe(strategy, chunks)
        rows.append(stats)
        print(f"  {strategy:<8} -> {len(chunks):>4} chunks   {path.name}")

    print()
    header = f"{'strategy':<9}{'chunks':>7}{'median':>8}{'p95':>7}{'max':>7}{'<200':>7}{'>3000':>7}{'sections':>10}"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['strategy']:<9}{r['chunks']:>7}{r['median_chars']:>8}{r['p95_chars']:>7}"
            f"{r['max_chars']:>7}{r['under_200']:>7}{r['over_3000']:>7}{r['sections_covered']:>10}"
        )

    if args.compare:
        print(
            "\nsections column = how many source sections each strategy can be labelled "
            "against;\nfixed scores 0 because it discards section boundaries entirely, "
            "which is the point of\nkeeping it as the baseline."
        )


if __name__ == "__main__":
    main()
