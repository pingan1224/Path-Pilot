"""Policy documents and their embedded chunks — the retrieval corpus."""

from __future__ import annotations

from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

# Dimensionality of the embedding model chosen in P3. Changing this requires re-embedding
# the whole corpus, so it lives in one place.
EMBEDDING_DIM = 1024


class Document(Base, TimestampMixin):
    """A source document in the retrieval corpus.

    Only publicly published policy pages go in here. Student-specific facts never become
    embedded text — they reach the model through the permission-checked tool layer instead
    (rule 1). That split is what keeps one student's record from ever surfacing in another
    student's retrieval.
    """

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    office: Mapped[str] = mapped_column(String(64), nullable=False)

    # Corpus facets, carried from the ingestion seed list. `scope` separates the home
    # school from the peer schools whose near-identical policy pages exist to make
    # retrieval discriminate rather than merely match.
    school: Mapped[str | None] = mapped_column(String(64), index=True)
    level: Mapped[str | None] = mapped_column(String(16))
    topic: Mapped[str | None] = mapped_column(String(32), index=True)
    scope: Mapped[str] = mapped_column(String(16), default="home", nullable=False)

    # True for documents we authored rather than fetched. Only the restricted-access
    # fixtures behind the leakage tests are synthetic: no genuinely internal university
    # document would be appropriate to scrape, and inventing public policy alongside real
    # policy would let the assistant cite a rule that does not exist.
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    published_at: Mapped[date | None] = mapped_column(Date)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Detects upstream edits without re-embedding unchanged documents on every crawl.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentChunk.ordinal",
    )


class DocumentChunk(Base):
    """One retrievable passage.

    `visible_to_roles` is the mechanism behind rule 3. Retrieval filters on this column in
    the same SQL statement as the vector search, so out-of-scope passages are excluded
    before ranking rather than stripped from the results afterwards. A passage the caller
    may not see is never a candidate, so it can never reach a prompt.
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "strategy", "ordinal", name="uq_chunk_position"),
        # GIN index makes the role pre-filter cheap enough to apply before ranking.
        Index("ix_chunk_roles", "visible_to_roles", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    # Which chunking strategy produced this row. All arms of an ablation live in the
    # table at once and retrieval filters on the active one, so comparing strategies is a
    # config flip rather than a reload-and-re-embed cycle.
    strategy: Mapped[str] = mapped_column(String(24), default="heading", nullable=False, index=True)

    # Source sections this chunk covers, as `slug#heading_path`. Eval labels point here
    # rather than at chunk ids: an ablation changes chunk boundaries by definition, so
    # id-based labels would break on every run.
    section_keys: Mapped[list[str]] = mapped_column(
        ARRAY(String(512)), nullable=False, server_default="{}"
    )

    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Breadcrumb of the headings this passage sat under, e.g.
    # "Registration > Holds > Financial". Cited alongside the document title so the student
    # can find the passage on the real page.
    heading_path: Mapped[str | None] = mapped_column(String(512))
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)

    visible_to_roles: Mapped[list[str]] = mapped_column(
        ARRAY(String(16)), nullable=False, server_default="{student,advisor,registrar,finance}"
    )

    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(64))
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped[Document] = relationship(back_populates="chunks")
