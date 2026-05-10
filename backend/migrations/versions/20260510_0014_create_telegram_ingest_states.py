"""create telegram ingest states

Revision ID: 20260510_0014
Revises: 20260506_0013
Create Date: 2026-05-10 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260510_0014"
down_revision = "20260506_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_ingest_states",
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("active_collection_id", sa.String(length=36), nullable=True),
        sa.Column("default_group_collection_id", sa.String(length=36), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["active_collection_id"],
            ["content_objects.id"],
            name=op.f("fk_telegram_ingest_states_active_collection_id_content_objects"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["default_group_collection_id"],
            ["content_objects.id"],
            name=op.f("fk_telegram_ingest_states_default_group_collection_id_content_objects"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_telegram_ingest_states_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("owner_user_id", name=op.f("pk_telegram_ingest_states")),
    )
    op.create_index(
        op.f("ix_telegram_ingest_states_active_collection_id"),
        "telegram_ingest_states",
        ["active_collection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_telegram_ingest_states_default_group_collection_id"),
        "telegram_ingest_states",
        ["default_group_collection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_telegram_ingest_states_last_message_at"),
        "telegram_ingest_states",
        ["last_message_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_telegram_ingest_states_last_message_at"), table_name="telegram_ingest_states"
    )
    op.drop_index(
        op.f("ix_telegram_ingest_states_default_group_collection_id"),
        table_name="telegram_ingest_states",
    )
    op.drop_index(
        op.f("ix_telegram_ingest_states_active_collection_id"),
        table_name="telegram_ingest_states",
    )
    op.drop_table("telegram_ingest_states")
