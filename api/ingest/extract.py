"""Stage 2 — HTML to a heading-structured section tree.

    .venv/Scripts/python -m ingest.extract
    .venv/Scripts/python -m ingest.extract --stats     # size distribution, no writing
    .venv/Scripts/python -m ingest.extract --show SLUG # print one page's sections

Reads data/raw/pages/*.html, writes data/sections/*.json. The output is committed to the
repo: eval labels reference this corpus, so reproducibility depends on the extracted text
being versioned rather than re-scraped.

What the extraction actually has to get right:

* **Boilerplate.** bulletins.nyu.edu runs CourseLeaf, which helpfully marks every
  non-content element with `class="notinpdf"` — the "On This Page" nav, print controls,
  sidebars. Dropping that class plus the usual script/style/nav removes the noise without
  hand-tuning selectors per page.
* **Heading hierarchy.** Policy text is written as nested rules, and a rule's meaning
  often lives in its ancestors ("Grading > Withdrawal (W)"). The heading path is carried
  into the chunk and prepended before embedding, because it is frequently the part that
  matches how people actually ask.
* **Tables.** Grading scales, fee schedules, and course lists are tables. Flattening them
  to prose destroys the row/column relationship that carries the meaning, so they are
  converted to Markdown and kept inline.
* **Lists.** Policy documents are list-heavy. Bullets are preserved as lines rather than
  run together, for the same reason.
* **Anchors.** Where a heading carries an id, it is recorded so a citation can deep-link
  to the exact section of the source page instead of just the page.
"""

import argparse
import json
import re
import statistics
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

from ingest.sources import by_slug

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PAGES_DIR = DATA_DIR / "raw" / "pages"
SECTIONS_DIR = DATA_DIR / "sections"
MANIFEST = DATA_DIR / "raw" / "manifest.json"

HEADING_TAGS = ("h1", "h2", "h3", "h4")
BLOCK_TAGS = ("p", "ul", "ol", "table", "blockquote", "dl", "pre")

# CourseLeaf marks chrome with `notinpdf`; the rest is the usual boilerplate.
DROP_SELECTORS = [
    ".notinpdf",
    "script",
    "style",
    "noscript",
    "nav",
    "footer",
    ".sr-only",
    ".skip",
    "#otp1",
    ".onthispage",
]

# Headings that are navigation furniture rather than content.
BOILERPLATE_HEADINGS = {"on this page", "print options", "search catalog"}


def clean_text(value: str) -> str:
    """Normalise whitespace, including the non-breaking spaces CourseLeaf emits."""
    return re.sub(r"[ \t]+", " ", value.replace("\xa0", " ")).strip()


def table_to_markdown(table: Tag) -> str:
    """Render a table as Markdown so row/column structure survives into the chunk."""
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append(cells)
    if not rows:
        return ""

    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]

    header, body = rows[0], rows[1:]
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)


def block_to_text(node: Tag) -> str:
    if node.name == "table":
        return table_to_markdown(node)
    if node.name in ("ul", "ol"):
        items = []
        for li in node.find_all("li", recursive=False):
            text = clean_text(li.get_text(" ", strip=True))
            if text:
                items.append(f"- {text}")
        return "\n".join(items)
    if node.name == "dl":
        parts = []
        for child in node.find_all(["dt", "dd"], recursive=False):
            text = clean_text(child.get_text(" ", strip=True))
            if text:
                parts.append(f"**{text}**" if child.name == "dt" else text)
        return "\n".join(parts)
    return clean_text(node.get_text(" ", strip=True))


def extract_course_blocks(container: Tag, page_title: str) -> list[dict]:
    """Course catalog pages are records, not prose, so they get their own handler.

    CourseLeaf renders each course as `.courseblock` with labelled `.detail-*` spans and
    no headings at all — which is why the generic heading walker returned nothing for the
    MASY1-GC catalog, the single most relevant page in the corpus. One course becomes one
    section: a course is already the unit a question is about ("what are the prerequisites
    for MASY1-GC 2XXX"), so splitting or merging it would only blur the answer.
    """
    sections: list[dict] = []

    for block in container.select(".courseblock"):
        code = block.select_one(".detail-code")
        title = block.select_one(".detail-title")
        code_text = clean_text(code.get_text(" ", strip=True)) if code else ""
        title_text = clean_text(title.get_text(" ", strip=True)) if title else ""
        if not code_text and not title_text:
            continue

        heading = f"{code_text} {title_text}".strip()
        parts: list[str] = []

        hours = block.select_one(".detail-hours_html")
        if hours:
            parts.append(f"Credits: {clean_text(hours.get_text(' ', strip=True))}")

        for extra in block.select(".courseblockextra"):
            text = clean_text(extra.get_text(" ", strip=True))
            if text:
                parts.append(text)

        # Labelled details, kept as explicit key/value lines so a chunk states plainly
        # that a course has prerequisites rather than burying it in prose.
        for selector, label in (
            (".detail-prerequisites", "Prerequisites"),
            (".detail-typically_offered", "Typically offered"),
            (".detail-grading", "Grading"),
            (".detail-repeatability", "Repeatability"),
        ):
            node = block.select_one(selector)
            if not node:
                continue
            text = clean_text(node.get_text(" ", strip=True))
            if not text:
                continue
            if not text.lower().startswith(label.split()[0].lower()):
                text = f"{label}: {text}"
            parts.append(text)

        body = "\n".join(p for p in parts if p).strip()
        if not body:
            continue

        anchor = block.get("id")
        sections.append(
            {
                "heading": heading,
                "level": 2,
                "heading_path": f"{page_title} > {heading}",
                "anchor": anchor,
                "text": body,
            }
        )

    return sections


def extract_sections(html: str, page_title_fallback: str) -> tuple[str, list[dict]]:
    soup = BeautifulSoup(html, "lxml")

    for selector in DROP_SELECTORS:
        for node in soup.select(selector):
            node.decompose()

    title_node = soup.select_one("h1.page-title") or soup.select_one("h1")
    page_title = clean_text(title_node.get_text(" ", strip=True)) if title_node else page_title_fallback

    # Program pages are tabbed: `#textcontainer` is only the first panel, and the degree
    # requirements live in sibling `.page_content` containers. Reading one container
    # silently returned the overview and dropped the requirements table — the extractor
    # produced a plausible-looking three-section page instead of failing.
    containers = soup.select("#textcontainer, .page_content") or [
        soup.select_one("main#contentarea") or soup.body
    ]
    containers = [c for c in containers if c is not None]
    if not containers:
        return page_title, []

    # Course catalogs carry no headings; dispatch on structure rather than on the URL, so
    # any page built from course blocks is handled the same way.
    for container in containers:
        if container.select_one(".courseblock"):
            return page_title, extract_course_blocks(container, page_title)

    sections: list[dict] = []
    # Heading stack: index 0 -> h1, 1 -> h2, ... Used to build the ancestry path.
    stack: list[str] = [page_title]
    current = {"heading": page_title, "level": 1, "anchor": None, "parts": [], "path": [page_title]}

    def flush() -> None:
        text = "\n\n".join(p for p in current["parts"] if p).strip()
        if text:
            sections.append(
                {
                    "heading": current["heading"],
                    "level": current["level"],
                    "heading_path": " > ".join(current["path"]),
                    "anchor": current["anchor"],
                    "text": text,
                }
            )

    # Walk every panel in document order; headings continue the same ancestry stack, so a
    # requirements table in tab two nests under the page title exactly as it reads.
    descendants = (node for container in containers for node in container.descendants)
    for node in descendants:
        if isinstance(node, NavigableString) or not isinstance(node, Tag):
            continue

        if node.name in HEADING_TAGS:
            heading = clean_text(node.get_text(" ", strip=True))
            if not heading or heading.lower() in BOILERPLATE_HEADINGS:
                continue
            flush()
            level = int(node.name[1])
            # Trim the ancestry to this heading's depth, then append.
            stack = stack[: max(level - 1, 1)]
            stack.append(heading)
            anchor = node.get("id")
            if not anchor:
                a = node.find("a", id=True)
                anchor = a.get("id") if a else None
            current = {
                "heading": heading,
                "level": level,
                "anchor": anchor,
                "parts": [],
                "path": list(stack),
            }
            continue

        if node.name in BLOCK_TAGS:
            # Skip blocks nested inside another block we will already capture.
            if node.find_parent(BLOCK_TAGS):
                continue
            text = block_to_text(node)
            if text:
                current["parts"].append(text)

    flush()
    return page_title, sections


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", action="store_true", help="report size distribution only")
    parser.add_argument("--show", type=str, default=None, help="print one page's sections")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sources = by_slug()
    SECTIONS_DIR.mkdir(parents=True, exist_ok=True)

    all_lengths: list[int] = []
    per_page: list[tuple[str, int, int]] = []
    written = 0

    for slug, meta in sorted(manifest.items()):
        path = PAGES_DIR / f"{slug}.html"
        if not path.exists():
            print(f"  skip {slug}: no cached HTML (run ingest.fetch)")
            continue

        source = sources.get(slug)
        html = path.read_text(encoding="utf-8")
        title, sections = extract_sections(html, slug)

        lengths = [len(s["text"]) for s in sections]
        all_lengths.extend(lengths)
        per_page.append((slug, len(sections), sum(lengths)))

        if args.show == slug:
            print(f"\n=== {title} ({len(sections)} sections) ===")
            for s in sections:
                preview = s["text"][:160].replace("\n", " ⏎ ")
                print(f"\n  [{s['level']}] {s['heading_path']}  ({len(s['text'])} chars)")
                print(f"      {preview}{'…' if len(s['text']) > 160 else ''}")
            continue

        if args.stats or args.show:
            continue

        payload = {
            "slug": slug,
            "url": meta["url"],
            "title": title,
            "school": meta["school"],
            "level": meta["level"],
            "topic": meta["topic"],
            "office": meta["office"],
            "scope": meta["scope"],
            "fetched_at": meta["fetched_at"],
            "sha256": meta["sha256"],
            "sections": sections,
        }
        (SECTIONS_DIR / f"{slug}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        written += 1

    if args.show:
        return

    print(f"\npages: {len(per_page)}   sections: {len(all_lengths)}   written: {written}")
    if all_lengths:
        ordered = sorted(all_lengths)
        print(
            f"section chars — min {ordered[0]}  p25 {ordered[len(ordered)//4]}  "
            f"median {statistics.median(ordered):.0f}  p75 {ordered[3*len(ordered)//4]}  "
            f"p95 {ordered[int(len(ordered)*0.95)]}  max {ordered[-1]}"
        )
        tiny = sum(1 for x in all_lengths if x < 200)
        huge = sum(1 for x in all_lengths if x > 3000)
        print(f"  under 200 chars: {tiny} ({tiny/len(all_lengths):.0%})   over 3000: {huge} ({huge/len(all_lengths):.0%})")
        print("\nlargest pages by extracted text:")
        for slug, n, total in sorted(per_page, key=lambda x: -x[2])[:6]:
            print(f"  {total:>7,}c  {n:>3} sections  {slug}")


if __name__ == "__main__":
    main()
