"""Embed every un-embedded document chunk.

    .venv/Scripts/python -m scripts.embed_corpus [--all]

Idempotent: only chunks with a NULL embedding are processed, so re-running after adding
documents embeds just the new ones. --all re-embeds everything (needed after changing the
embedding model). The model name is stored per chunk, so a mixed-model corpus is
detectable rather than silent.
"""

import argparse
from datetime import UTC, datetime

from sqlalchemy import select

from app.config import settings
from app.db.session import get_sessionmaker
from app.models import DocumentChunk
from app.services.embeddings import embed

BATCH = 32


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="re-embed every chunk")
    args = parser.parse_args()

    with get_sessionmaker()() as session:
        query = select(DocumentChunk).order_by(DocumentChunk.id)
        if not args.all:
            query = query.where(DocumentChunk.embedding.is_(None))
        chunks = session.scalars(query).all()

        if not chunks:
            print("nothing to embed")
            return

        print(f"embedding {len(chunks)} chunks with {settings.embedding_model} ...")
        done = 0
        for start in range(0, len(chunks), BATCH):
            batch = chunks[start : start + BATCH]
            # Heading path is prepended so the vector carries the document's own structure
            # ("Registration > Holds > Financial holds: ..."), which is often the part of
            # the text that actually matches how people ask.
            texts = [
                f"{c.heading_path}: {c.text}" if c.heading_path else c.text for c in batch
            ]
            vectors = embed(texts)
            now = datetime.now(UTC)
            for chunk, vector in zip(batch, vectors):
                chunk.embedding = vector
                chunk.embedding_model = settings.embedding_model
                chunk.embedded_at = now
            done += len(batch)
            print(f"  {done}/{len(chunks)}")

        session.commit()
    print("done.")


if __name__ == "__main__":
    main()
