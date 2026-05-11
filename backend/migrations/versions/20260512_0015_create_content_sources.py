"""create universal content source records

Revision ID: 20260512_0015
Revises: 20260510_0014
Create Date: 2026-05-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260512_0015"
down_revision = "20260510_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("content_object_id", sa.String(length=36), nullable=False),
        sa.Column("content_asset_id", sa.String(length=36), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_label", sa.String(length=128), nullable=False),
        sa.Column("external_id", sa.String(length=512), nullable=False),
        sa.Column("group_id", sa.String(length=512), nullable=True),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("original_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("origin", sa.JSON(), nullable=True),
        sa.Column("author", sa.JSON(), nullable=True),
        sa.Column("entities", sa.JSON(), nullable=True),
        sa.Column("custom_emoji_ids", sa.JSON(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["content_asset_id"],
            ["content_assets.id"],
            name=op.f("fk_content_sources_content_asset_id_content_assets"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["content_object_id"],
            ["content_objects.id"],
            name=op.f("fk_content_sources_content_object_id_content_objects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_content_sources_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_content_sources")),
        sa.UniqueConstraint(
            "provider",
            "external_id",
            "content_object_id",
            name="uq_content_sources_provider_external_object",
        ),
    )
    op.create_index(op.f("ix_content_sources_content_asset_id"), "content_sources", ["content_asset_id"])
    op.create_index(
        op.f("ix_content_sources_content_object_id"),
        "content_sources",
        ["content_object_id"],
    )
    op.create_index(op.f("ix_content_sources_external_id"), "content_sources", ["external_id"])
    op.create_index(op.f("ix_content_sources_group_id"), "content_sources", ["group_id"])
    op.create_index(
        op.f("ix_content_sources_original_created_at"),
        "content_sources",
        ["original_created_at"],
    )
    op.create_index(op.f("ix_content_sources_owner_user_id"), "content_sources", ["owner_user_id"])
    op.create_index(op.f("ix_content_sources_provider"), "content_sources", ["provider"])

    op.add_column(
        "telegram_ingest_states",
        sa.Column("source_group_collection_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "telegram_ingest_states",
        sa.Column("source_group_key", sa.String(length=640), nullable=True),
    )
    op.add_column(
        "telegram_ingest_states",
        sa.Column("source_group_last_message_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_telegram_ingest_states_source_group_collection_id_content_objects"),
        "telegram_ingest_states",
        "content_objects",
        ["source_group_collection_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_telegram_ingest_states_source_group_collection_id"),
        "telegram_ingest_states",
        ["source_group_collection_id"],
    )
    op.create_index(
        op.f("ix_telegram_ingest_states_source_group_key"),
        "telegram_ingest_states",
        ["source_group_key"],
    )
    op.create_index(
        op.f("ix_telegram_ingest_states_source_group_last_message_at"),
        "telegram_ingest_states",
        ["source_group_last_message_at"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_telegram_ingest_states_source_group_last_message_at"),
        table_name="telegram_ingest_states",
    )
    op.drop_index(
        op.f("ix_telegram_ingest_states_source_group_key"),
        table_name="telegram_ingest_states",
    )
    op.drop_index(
        op.f("ix_telegram_ingest_states_source_group_collection_id"),
        table_name="telegram_ingest_states",
    )
    op.drop_constraint(
        op.f("fk_telegram_ingest_states_source_group_collection_id_content_objects"),
        "telegram_ingest_states",
        type_="foreignkey",
    )
    op.drop_column("telegram_ingest_states", "source_group_last_message_at")
    op.drop_column("telegram_ingest_states", "source_group_key")
    op.drop_column("telegram_ingest_states", "source_group_collection_id")

    op.drop_index(op.f("ix_content_sources_provider"), table_name="content_sources")
    op.drop_index(op.f("ix_content_sources_owner_user_id"), table_name="content_sources")
    op.drop_index(op.f("ix_content_sources_original_created_at"), table_name="content_sources")
    op.drop_index(op.f("ix_content_sources_group_id"), table_name="content_sources")
    op.drop_index(op.f("ix_content_sources_external_id"), table_name="content_sources")
    op.drop_index(op.f("ix_content_sources_content_object_id"), table_name="content_sources")
    op.drop_index(op.f("ix_content_sources_content_asset_id"), table_name="content_sources")
    op.drop_table("content_sources")
