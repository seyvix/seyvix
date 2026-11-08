"""Move pgvector embeddings to the configured dimension and queue re-embedding.

Revision ID: 0002_embedding_dimensions_1024
Revises: 0001_baseline
Create Date: 2026-11-08

Old vectors are incompatible with the new embedding model/dimensions. Clear only those vectors;
keep chunk text and mark sources for embedding again. The old dimension is saved in the column
comment so downgrade can restore the exact schema that was present before this migration.
"""

from __future__ import annotations

import re

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

from app.core.config import get_settings

revision = "0002_embedding_dimensions_1024"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

EMBEDDING_INDEX = "ix_vectorization_chunks_embedding_hnsw"
TARGET_DIMENSIONS = get_settings().ai_embedding_dimensions
DIMENSION_COMMENT_PREFIX = "seyvix:previous-embedding-dimensions="


def _current_dimensions() -> int:
    formatted_type = op.get_bind().execute(
        sa.text(
            """
            SELECT format_type(attribute.atttypid, attribute.atttypmod)
            FROM pg_attribute AS attribute
            WHERE attribute.attrelid = 'vectorization_chunks'::regclass
              AND attribute.attname = 'embedding'
              AND NOT attribute.attisdropped
            """
        )
    ).scalar_one()
    match = re.fullmatch(r"halfvec\((\d+)\)", formatted_type)
    if match is None:
        raise RuntimeError(f"Unexpected vectorization_chunks.embedding type: {formatted_type}")
    return int(match.group(1))


def _create_embedding_index() -> None:
    op.create_index(
        EMBEDDING_INDEX,
        "vectorization_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "halfvec_cosine_ops"},
    )


def _reset_vectors() -> None:
    op.execute("UPDATE vectorization_chunks SET embedding = NULL")
    op.execute(
        """
        UPDATE vectorization_sources
        SET embedding_model = NULL,
            needs_embedding = (chunk_count > 0),
            last_error = NULL
        """
    )


def upgrade() -> None:
    previous_dimensions = _current_dimensions()
    if previous_dimensions == TARGET_DIMENSIONS:
        return

    op.execute(
        "COMMENT ON COLUMN vectorization_chunks.embedding IS "
        f"'{DIMENSION_COMMENT_PREFIX}{previous_dimensions}'"
    )
    op.drop_index(EMBEDDING_INDEX, table_name="vectorization_chunks")
    _reset_vectors()
    op.alter_column(
        "vectorization_chunks",
        "embedding",
        existing_type=pgvector.sqlalchemy.HALFVEC(dim=previous_dimensions),
        type_=pgvector.sqlalchemy.HALFVEC(dim=TARGET_DIMENSIONS),
        postgresql_using=f"NULL::halfvec({TARGET_DIMENSIONS})",
    )
    _create_embedding_index()


def downgrade() -> None:
    comment = op.get_bind().execute(
        sa.text(
            """
            SELECT col_description(attribute.attrelid, attribute.attnum)
            FROM pg_attribute AS attribute
            WHERE attribute.attrelid = 'vectorization_chunks'::regclass
              AND attribute.attname = 'embedding'
              AND NOT attribute.attisdropped
            """
        )
    ).scalar_one_or_none()
    match = (
        re.fullmatch(re.escape(DIMENSION_COMMENT_PREFIX) + r"(\d+)", comment)
        if isinstance(comment, str)
        else None
    )
    if comment is None:
        return
    if match is None:
        raise RuntimeError("Previous embedding dimension marker is missing from the column comment")
    previous_dimensions = int(match.group(1))
    current_dimensions = _current_dimensions()
    if current_dimensions == previous_dimensions:
        op.execute("COMMENT ON COLUMN vectorization_chunks.embedding IS NULL")
        return

    op.drop_index(EMBEDDING_INDEX, table_name="vectorization_chunks")
    _reset_vectors()
    op.alter_column(
        "vectorization_chunks",
        "embedding",
        existing_type=pgvector.sqlalchemy.HALFVEC(dim=current_dimensions),
        type_=pgvector.sqlalchemy.HALFVEC(dim=previous_dimensions),
        postgresql_using=f"NULL::halfvec({previous_dimensions})",
    )
    op.execute("COMMENT ON COLUMN vectorization_chunks.embedding IS NULL")
    _create_embedding_index()
