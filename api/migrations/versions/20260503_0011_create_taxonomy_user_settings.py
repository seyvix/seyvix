"""create taxonomy user settings

Revision ID: 20260503_0011
Revises: 20260503_0010
Create Date: 2026-05-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260503_0011"
down_revision = "20260503_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "taxonomy_user_settings",
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("category_profile_editing_enabled", sa.Boolean(), nullable=False),
        sa.Column("trash_enabled", sa.Boolean(), nullable=False),
        sa.Column("trash_retention_days", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("owner_user_id"),
    )


def downgrade() -> None:
    op.drop_table("taxonomy_user_settings")
