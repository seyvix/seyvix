"""Search index storage: one row per indexed item, its text chunks, and the index job queue.

Storage decisions:
- Chunk text is stored exactly once (`vectorization_chunks.text`); there is no document copy
  and no per-chunk metadata copy. Filters join the live source tables instead.
- The FTS vector is a STORED generated column, so the GIN index and the query use the very
  same expression by construction.
- Embeddings live on the chunk as `halfvec(AI_EMBEDDING_DIMENSIONS)`: half the storage of
  `vector`, HNSW-indexable up to 4000 dimensions (vector: 2000), and float16 precision does
  not measurably change cosine ranking of normalized text embeddings.
- A NULL embedding means "not embedded yet" (AI disabled, outage, or new chunk); the job
  runner's embedding loop fills them in. Non-NULL embeddings were always produced by
  `VectorizationSource.embedding_model`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pgvector.sqlalchemy import HALFVEC  # type: ignore[import-untyped]
from sqlalchemy import (
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import get_settings
from app.core.database import Base
from app.platform.jobs import JobColumnsMixin, job_queue_indexes, utcnow

_settings = get_settings()
EMBEDDING_DIMENSIONS = _settings.ai_embedding_dimensions
FTS_CONFIG = _settings.search_fts_config  # validated by Settings (lowercase identifier)


def _uuid() -> str:
    return str(uuid4())


class VectorizationSource(Base):
    """One indexed item (a note, a taxonomy category profile, ...)."""

    __tablename__ = "vectorization_sources"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "source",
            "source_type",
            "source_id",
            name="uq_vectorization_sources_scope",
        ),
        Index(
            "ix_vectorization_sources_needs_embedding",
            "updated_at",
            postgresql_where=text("needs_embedding"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(64))
    source_type: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(255))
    # sha256 of chunking config + indexed text: unchanged hash => nothing to do.
    content_hash: Mapped[str] = mapped_column(String(64))
    chunk_count: Mapped[int] = mapped_column(Integer(), default=0)
    needs_embedding: Mapped[bool] = mapped_column(Boolean(), default=False)
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class VectorizationChunk(Base):
    __tablename__ = "vectorization_chunks"
    __table_args__ = (
        UniqueConstraint(
            "source_record_id", "chunk_index", name="uq_vectorization_chunks_source_index"
        ),
        Index("ix_vectorization_chunks_owner", "owner_user_id"),
        Index("ix_vectorization_chunks_search_vector", "search_vector", postgresql_using="gin"),
        Index(
            "ix_vectorization_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "halfvec_cosine_ops"},
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_record_id: Mapped[str] = mapped_column(
        ForeignKey("vectorization_sources.id", ondelete="CASCADE")
    )
    # Denormalized from the source so owner-scoped scans need no join.
    owner_user_id: Mapped[str] = mapped_column(String(36))
    chunk_index: Mapped[int] = mapped_column(Integer())
    text: Mapped[str] = mapped_column(Text())
    text_hash: Mapped[str] = mapped_column(String(32))
    token_count: Mapped[int] = mapped_column(Integer())
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR(),
        Computed(f"to_tsvector('{FTS_CONFIG}'::regconfig, text)", persisted=True),
        deferred=True,
    )
    embedding: Mapped[Any | None] = mapped_column(
        HALFVEC(EMBEDDING_DIMENSIONS), nullable=True, deferred=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VectorizationJob(JobColumnsMixin, Base):
    """At most one row per indexed item; re-enqueue resets it (duplicate-safe upsert)."""

    __tablename__ = "vectorization_jobs"
    __table_args__ = (
        *job_queue_indexes("vectorization_jobs"),
        UniqueConstraint(
            "owner_user_id",
            "source",
            "source_type",
            "source_id",
            name="uq_vectorization_jobs_scope",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(64))
    source_type: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(255))
