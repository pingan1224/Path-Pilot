"""Stage 4 — load chunked corpus into Postgres.

    .venv/Scripts/python -m ingest.load --strategy heading
    .venv/Scripts/python -m ingest.load --all          # every strategy, one pass
    .venv/Scripts/python -m ingest.load --all --embed  # and embed what it wrote

Every strategy is stored side by side, distinguished by `document_chunks.strategy`.
Retrieval filters on `settings.chunk_strategy`, so comparing chunking approaches is a
config flip and a re-run of the eval rather than a reload-and-re-embed cycle.

Synthetic documents (the restricted-access fixtures the leakage tests need) are never
touched here — this loader owns only the ingested corpus, and deletes only what it owns.

Role visibility: everything fetched from bulletins.nyu.edu is publicly published, so every
chunk is visible to every role. Stating that as a rule rather than hand-assigning ~1,000
rows is the only way the assignment stays correct as the corpus grows; the interesting
restricted case lives in the synthetic fixtures.
"""

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select

from app.db.session import get_sessionmaker
from app.models import Document, DocumentChunk

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CHUNKS_DIR = DATA_DIR / "chunks"
MANIFEST = DATA_DIR / "raw" / "manifest.json"

ALL_ROLES = ["student", "advisor"]


def load_manifest() -> dict[str, dict]:
    """Fetch-time provenance, keyed by slug.

    The document's content_hash and fetched_at come from here rather than being invented
    at load time: they record when this text was actually taken from the source, which is
    what makes a citation's freshness claim true rather than decorative.
    """
    if not MANIFEST.exists():
        return {}
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def load_strategy(session, strategy: str) -> tuple[int, int]:
    path = CHUNKS_DIR / f"{strategy}.json"
    if not path.exists():
        raise SystemExit(f"{path} not found. Run `python -m ingest.chunk --strategy {strategy}`.")

    payload = json.loads(path.read_text(encoding="utf-8"))
    chunks = payload["chunks"]
    manifest = load_manifest()

    # Group by source page: one Document row per page, shared across strategies.
    by_slug: dict[str, list[dict]] = {}
    for chunk in chunks:
        by_slug.setdefault(chunk["slug"], []).append(chunk)

    documents = 0
    written = 0
    for slug, page_chunks in by_slug.items():
        first = page_chunks[0]

        document = session.scalars(
            select(Document).where(Document.url == first["url"], Document.is_synthetic.is_(False))
        ).first()

        if document is None:
            provenance = manifest.get(slug, {})
            fetched_at = provenance.get("fetched_at")
            document = Document(
                source_key="policy_doc",
                title=first["page_title"],
                url=first["url"],
                office=first["office"],
                school=first["school"],
                level=first["level"],
                topic=first["topic"],
                scope=first["scope"],
                is_synthetic=False,
                published_at=None,
                fetched_at=(
                    datetime.fromisoformat(fetched_at) if fetched_at else datetime.now(UTC)
                ),
                content_hash=provenance.get("sha256", "")[:64],
                is_active=True,
            )
            session.add(document)
            session.flush()
            documents += 1

        # Replace only this strategy's rows for this document.
        session.execute(
            delete(DocumentChunk).where(
                DocumentChunk.document_id == document.id,
                DocumentChunk.strategy == strategy,
            )
        )

        for ordinal, chunk in enumerate(page_chunks):
            session.add(
                DocumentChunk(
                    document_id=document.id,
                    strategy=strategy,
                    ordinal=ordinal,
                    text=chunk["text"],
                    heading_path=chunk["heading_path"],
                    section_keys=chunk["section_keys"],
                    token_count=max(chunk["char_count"] // 4, 1),
                    visible_to_roles=list(ALL_ROLES),
                )
            )
            written += 1

    session.commit()
    return documents, written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", default="heading")
    parser.add_argument("--all", action="store_true", help="load every strategy present")
    parser.add_argument("--embed", action="store_true", help="run scripts.embed_corpus afterwards")
    args = parser.parse_args()

    available = sorted(p.stem for p in CHUNKS_DIR.glob("*.json"))
    targets = available if args.all else [args.strategy]
    if not targets:
        raise SystemExit("No chunk files found. Run `python -m ingest.chunk --compare` first.")

    with get_sessionmaker()() as session:
        for strategy in targets:
            docs, chunks = load_strategy(session, strategy)
            print(f"  {strategy:<8} {chunks:>5} chunks  (+{docs} new documents)")

        totals = session.execute(
            select(DocumentChunk.strategy, Document.is_synthetic)
            .join(Document, Document.id == DocumentChunk.document_id)
        ).all()

    counts: dict[tuple[str, bool], int] = {}
    for strategy, synthetic in totals:
        counts[(strategy, synthetic)] = counts.get((strategy, synthetic), 0) + 1

    print("\nin database:")
    for (strategy, synthetic), n in sorted(counts.items()):
        kind = "synthetic" if synthetic else "ingested"
        print(f"  {strategy:<8} {kind:<10} {n:>5}")

    if args.embed:
        print("\nembedding ...")
        subprocess.run([sys.executable, "-m", "scripts.embed_corpus"], check=True)


if __name__ == "__main__":
    main()
