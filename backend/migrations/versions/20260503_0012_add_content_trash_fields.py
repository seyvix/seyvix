"""add content trash fields

Revision ID: 20260503_0012
Revises: 20260503_0011
Create Date: 2026-05-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260503_0012"
down_revision = "20260503_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_objects", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "content_objects", sa.Column("delete_after", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        op.f("ix_content_objects_deleted_at"),
        "content_objects",
        ["deleted_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_content_objects_deleted_at"), table_name="content_objects")
    op.drop_column("content_objects", "delete_after")
    op.drop_column("content_objects", "deleted_at")
