"""create vectorization tables

Revision ID: 20260429_0007
Revises: 20260429_0006
Create Date: 2026-04-29 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "20260429_0007"
down_revision = "20260429_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "vectorization_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("external_id", sa.String(length=512), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("dimensions", sa.Integer(), nullable=True),
        sa.Column("last_indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_vectorization_sources_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vectorization_sources")),
        sa.UniqueConstraint(
            "owner_user_id",
            "external_id",
            name="uq_vectorization_sources_owner_external_id",
        ),
    )
    op.create_index(
        op.f("ix_vectorization_sources_owner_user_id"),
        "vectorization_sources",
        ["owner_user_id"],
    )
    op.create_index(
        "ix_vectorization_sources_owner_source",
        "vectorization_sources",
        ["owner_user_id", "source", "source_type"],
    )
    op.create_index(
        "ix_vectorization_sources_status",
        "vectorization_sources",
        ["status"],
    )

    op.create_table(
        "vectorization_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("source_record_id", sa.String(length=36), nullable=False),
        sa.Column("external_id", sa.String(length=512), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("chunking_strategy", sa.String(length=64), nullable=False),
        sa.Column("representation_type", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_vectorization_documents_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["vectorization_sources.id"],
            name=op.f("fk_vectorization_documents_source_record_id_vectorization_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vectorization_documents")),
        sa.UniqueConstraint(
            "source_record_id",
            name="uq_vectorization_documents_source_record_id",
        ),
    )
    op.create_index(
        op.f("ix_vectorization_documents_owner_user_id"),
        "vectorization_documents",
        ["owner_user_id"],
    )
    op.create_index(
        op.f("ix_vectorization_documents_source_record_id"),
        "vectorization_documents",
        ["source_record_id"],
    )

    op.create_table(
        "vectorization_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("source_record_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_external_id", sa.String(length=640), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_vectorization_chunks_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["vectorization_sources.id"],
            name=op.f("fk_vectorization_chunks_source_record_id_vectorization_sources"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["vectorization_documents.id"],
            name=op.f("fk_vectorization_chunks_document_id_vectorization_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vectorization_chunks")),
        sa.UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_vectorization_chunks_document_index",
        ),
        sa.UniqueConstraint(
            "owner_user_id",
            "chunk_external_id",
            name="uq_vectorization_chunks_owner_external_id",
        ),
    )
    op.create_index(
        op.f("ix_vectorization_chunks_owner_user_id"),
        "vectorization_chunks",
        ["owner_user_id"],
    )
    op.create_index(
        op.f("ix_vectorization_chunks_source_record_id"),
        "vectorization_chunks",
        ["source_record_id"],
    )
    op.create_index(
        op.f("ix_vectorization_chunks_document_id"),
        "vectorization_chunks",
        ["document_id"],
    )

    op.create_table(
        "vectorization_embeddings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
        sa.Column("embedding_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_vectorization_embeddings_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["vectorization_chunks.id"],
            name=op.f("fk_vectorization_embeddings_chunk_id_vectorization_chunks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vectorization_embeddings")),
        sa.UniqueConstraint(
            "chunk_id",
            "provider",
            "model",
            "dimensions",
            name="uq_vectorization_embeddings_chunk_provider_model_dimensions",
        ),
    )
    op.create_index(
        op.f("ix_vectorization_embeddings_owner_user_id"),
        "vectorization_embeddings",
        ["owner_user_id"],
    )
    op.create_index(
        op.f("ix_vectorization_embeddings_chunk_id"),
        "vectorization_embeddings",
        ["chunk_id"],
    )

    op.create_table(
        "vectorization_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("external_id", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=255), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_vectorization_jobs_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vectorization_jobs")),
    )
    op.create_index(
        op.f("ix_vectorization_jobs_owner_user_id"),
        "vectorization_jobs",
        ["owner_user_id"],
    )
    op.create_index(
        op.f("ix_vectorization_jobs_status"),
        "vectorization_jobs",
        ["status"],
    )
    op.create_index(
        "ix_vectorization_jobs_status_run_after_priority",
        "vectorization_jobs",
        ["status", "run_after", "priority"],
    )
    op.create_index(
        "ix_vectorization_jobs_owner_source",
        "vectorization_jobs",
        ["owner_user_id", "source", "source_type", "source_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_vectorization_jobs_owner_source", table_name="vectorization_jobs")
    op.drop_index(
        "ix_vectorization_jobs_status_run_after_priority", table_name="vectorization_jobs"
    )
    op.drop_index(op.f("ix_vectorization_jobs_status"), table_name="vectorization_jobs")
    op.drop_index(op.f("ix_vectorization_jobs_owner_user_id"), table_name="vectorization_jobs")
    op.drop_table("vectorization_jobs")
    op.drop_index(
        op.f("ix_vectorization_embeddings_chunk_id"),
        table_name="vectorization_embeddings",
    )
    op.drop_index(
        op.f("ix_vectorization_embeddings_owner_user_id"),
        table_name="vectorization_embeddings",
    )
    op.drop_table("vectorization_embeddings")
    op.drop_index(op.f("ix_vectorization_chunks_document_id"), table_name="vectorization_chunks")
    op.drop_index(
        op.f("ix_vectorization_chunks_source_record_id"),
        table_name="vectorization_chunks",
    )
    op.drop_index(op.f("ix_vectorization_chunks_owner_user_id"), table_name="vectorization_chunks")
    op.drop_table("vectorization_chunks")
    op.drop_index(
        op.f("ix_vectorization_documents_source_record_id"),
        table_name="vectorization_documents",
    )
    op.drop_index(
        op.f("ix_vectorization_documents_owner_user_id"),
        table_name="vectorization_documents",
    )
    op.drop_table("vectorization_documents")
    op.drop_index("ix_vectorization_sources_status", table_name="vectorization_sources")
    op.drop_index("ix_vectorization_sources_owner_source", table_name="vectorization_sources")
    op.drop_index(
        op.f("ix_vectorization_sources_owner_user_id"),
        table_name="vectorization_sources",
    )
    op.drop_table("vectorization_sources")
    op.execute("DROP EXTENSION IF EXISTS vector")
