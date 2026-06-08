"""create link snapshot decision records

Revision ID: 20260608_0017
Revises: 20260517_0016
Create Date: 2026-06-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260608_0017"
down_revision = "20260517_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_link_snapshot_decisions",
        sa.Column("content_object_id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["content_object_id"],
            ["content_objects.id"],
            name=op.f("fk_content_link_snapshot_decisions_content_object_id_content_objects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_content_link_snapshot_decisions_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "content_object_id",
            name=op.f("pk_content_link_snapshot_decisions"),
        ),
    )
    op.create_index(
        op.f("ix_content_link_snapshot_decisions_owner_user_id"),
        "content_link_snapshot_decisions",
        ["owner_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_content_link_snapshot_decisions_owner_user_id"),
        table_name="content_link_snapshot_decisions",
    )
    op.drop_table("content_link_snapshot_decisions")
