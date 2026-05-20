"""add hybrid search indexes

Revision ID: 20260517_0016
Revises: 20260512_0015
Create Date: 2026-05-17 12:00:00
"""

from __future__ import annotations

from alembic import op

revision = "20260517_0016"
down_revision = "20260512_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_vectorization_embeddings_embedding_384_hnsw "
        "ON vectorization_embeddings USING hnsw "
        "((embedding::vector(384)) vector_cosine_ops) "
        "WHERE dimensions = 384"
    )
    op.execute(
        "CREATE INDEX ix_vectorization_embeddings_embedding_1024_hnsw "
        "ON vectorization_embeddings USING hnsw "
        "((embedding::vector(1024)) vector_cosine_ops) "
        "WHERE dimensions = 1024"
    )
    op.execute(
        "CREATE INDEX ix_vectorization_chunks_text_fts "
        "ON vectorization_chunks USING gin (to_tsvector('simple', text))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_vectorization_chunks_text_fts")
    op.execute("DROP INDEX IF EXISTS ix_vectorization_embeddings_embedding_1024_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_vectorization_embeddings_embedding_384_hnsw")
