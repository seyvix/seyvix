"""add image_width and image_height to content_assets

Revision ID: 20260503_0010
Revises: 20260501_0009
Create Date: 2026-05-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260503_0010"
down_revision = "20260501_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("content_assets", sa.Column("image_width", sa.Integer(), nullable=True))
    op.add_column("content_assets", sa.Column("image_height", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("content_assets", "image_height")
    op.drop_column("content_assets", "image_width")
