from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class VectorizationSource(Base):
    __tablename__ = "vectorization_sources"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "external_id",
            name="uq_vectorization_sources_owner_external_id",
        ),
        Index("ix_vectorization_sources_owner_source", "owner_user_id", "source", "source_type"),
        Index("ix_vectorization_sources_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    source: Mapped[str] = mapped_column(String(64))
    source_type: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(255))
    external_id: Mapped[str] = mapped_column(String(512))
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dimensions: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    document: Mapped[VectorizationDocument | None] = relationship(
        back_populates="source_record",
        cascade="all, delete-orphan",
    )


class VectorizationDocument(Base):
    __tablename__ = "vectorization_documents"
    __table_args__ = (
        UniqueConstraint("source_record_id", name="uq_vectorization_documents_source_record_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    source_record_id: Mapped[str] = mapped_column(
        ForeignKey("vectorization_sources.id", ondelete="CASCADE"),
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(512))
    text: Mapped[str] = mapped_column(Text())
    text_hash: Mapped[str] = mapped_column(String(64))
    metadata_: Mapped[dict[str, object]] = mapped_column("metadata", JSON(), default=dict)
    chunking_strategy: Mapped[str] = mapped_column(String(64))
    representation_type: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    source_record: Mapped[VectorizationSource] = relationship(back_populates="document")
    chunks: Mapped[list[VectorizationChunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )


class VectorizationChunk(Base):
    __tablename__ = "vectorization_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_vectorization_chunks_document_index",
        ),
        UniqueConstraint(
            "owner_user_id",
            "chunk_external_id",
            name="uq_vectorization_chunks_owner_external_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    source_record_id: Mapped[str] = mapped_column(
        ForeignKey("vectorization_sources.id", ondelete="CASCADE"),
        index=True,
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("vectorization_documents.id", ondelete="CASCADE"),
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer())
    chunk_external_id: Mapped[str] = mapped_column(String(640))
    text: Mapped[str] = mapped_column(Text())
    text_hash: Mapped[str] = mapped_column(String(64))
    token_count: Mapped[int] = mapped_column(Integer())
    metadata_: Mapped[dict[str, object]] = mapped_column("metadata", JSON(), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    document: Mapped[VectorizationDocument] = relationship(back_populates="chunks")
    embedding: Mapped[VectorizationEmbedding | None] = relationship(
        back_populates="chunk",
        cascade="all, delete-orphan",
    )


class VectorizationEmbedding(Base):
    __tablename__ = "vectorization_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "chunk_id",
            "provider",
            "model",
            "dimensions",
            name="uq_vectorization_embeddings_chunk_provider_model_dimensions",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    chunk_id: Mapped[str] = mapped_column(
        ForeignKey("vectorization_chunks.id", ondelete="CASCADE"),
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(255))
    dimensions: Mapped[int] = mapped_column(Integer())
    embedding: Mapped[list[float]] = mapped_column(Vector())
    embedding_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    chunk: Mapped[VectorizationChunk] = relationship(back_populates="embedding")


class VectorizationJob(Base):
    __tablename__ = "vectorization_jobs"
    __table_args__ = (
        Index(
            "ix_vectorization_jobs_status_run_after_priority",
            "status",
            "run_after",
            "priority",
        ),
        Index(
            "ix_vectorization_jobs_owner_source",
            "owner_user_id",
            "source",
            "source_type",
            "source_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    job_type: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(64))
    source_type: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(255))
    external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    priority: Mapped[int] = mapped_column(Integer(), default=100)
    attempts: Mapped[int] = mapped_column(Integer(), default=0)
    max_attempts: Mapped[int] = mapped_column(Integer(), default=3)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
