"""create content tables

Revision ID: 20260424_0002
Revises: 20260423_0001
Create Date: 2026-04-24 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260424_0002"
down_revision = "20260423_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_categories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_content_categories_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["content_categories.id"],
            name=op.f("fk_content_categories_parent_id_content_categories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_content_categories")),
        sa.UniqueConstraint(
            "owner_user_id",
            "path",
            name="uq_content_categories_owner_user_id_path",
        ),
    )
    op.create_index(
        op.f("ix_content_categories_owner_user_id"),
        "content_categories",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_categories_parent_id"),
        "content_categories",
        ["parent_id"],
        unique=False,
    )

    op.create_table(
        "content_tags",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("tag_type", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_content_tags_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_content_tags")),
        sa.UniqueConstraint("owner_user_id", "slug", name="uq_content_tags_owner_user_id_slug"),
    )
    op.create_index(
        op.f("ix_content_tags_owner_user_id"),
        "content_tags",
        ["owner_user_id"],
        unique=False,
    )

    op.create_table(
        "content_objects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("category_id", sa.String(length=36), nullable=True),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("media_type", sa.String(length=32), nullable=True),
        sa.Column("source_filename", sa.String(length=512), nullable=True),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("storage_path", sa.String(length=2048), nullable=False),
        sa.Column("is_favorite", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["content_categories.id"],
            name=op.f("fk_content_objects_category_id_content_categories"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_content_objects_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_content_objects")),
        sa.UniqueConstraint("owner_user_id", "slug", name="uq_content_objects_owner_user_id_slug"),
    )
    op.create_index(
        op.f("ix_content_objects_category_id"),
        "content_objects",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_objects_created_at"),
        "content_objects",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_objects_kind"),
        "content_objects",
        ["kind"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_objects_media_type"),
        "content_objects",
        ["media_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_objects_owner_user_id"),
        "content_objects",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_objects_sort_order"),
        "content_objects",
        ["sort_order"],
        unique=False,
    )

    op.create_table(
        "content_assets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("content_object_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.String(length=2048), nullable=False),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["content_object_id"],
            ["content_objects.id"],
            name=op.f("fk_content_assets_content_object_id_content_objects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_content_assets")),
    )
    op.create_index(
        op.f("ix_content_assets_content_object_id"),
        "content_assets",
        ["content_object_id"],
        unique=False,
    )

    op.create_table(
        "content_collection_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("collection_id", sa.String(length=36), nullable=False),
        sa.Column("content_object_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["content_objects.id"],
            name=op.f("fk_content_collection_items_collection_id_content_objects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["content_object_id"],
            ["content_objects.id"],
            name=op.f("fk_content_collection_items_content_object_id_content_objects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_content_collection_items")),
        sa.UniqueConstraint(
            "content_object_id",
            name="uq_content_collection_items_content_object_id",
        ),
    )
    op.create_index(
        op.f("ix_content_collection_items_collection_id"),
        "content_collection_items",
        ["collection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_collection_items_content_object_id"),
        "content_collection_items",
        ["content_object_id"],
        unique=False,
    )

    op.create_table(
        "content_object_tags",
        sa.Column("content_object_id", sa.String(length=36), nullable=False),
        sa.Column("tag_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["content_object_id"],
            ["content_objects.id"],
            name=op.f("fk_content_object_tags_content_object_id_content_objects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["content_tags.id"],
            name=op.f("fk_content_object_tags_tag_id_content_tags"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("content_object_id", "tag_id", name=op.f("pk_content_object_tags")),
        sa.UniqueConstraint(
            "content_object_id", "tag_id", name="uq_content_object_tags_object_tag"
        ),
    )


def downgrade() -> None:
    op.drop_table("content_object_tags")
    op.drop_index(
        op.f("ix_content_collection_items_content_object_id"),
        table_name="content_collection_items",
    )
    op.drop_index(
        op.f("ix_content_collection_items_collection_id"),
        table_name="content_collection_items",
    )
    op.drop_table("content_collection_items")
    op.drop_index(op.f("ix_content_assets_content_object_id"), table_name="content_assets")
    op.drop_table("content_assets")
    op.drop_index(op.f("ix_content_objects_sort_order"), table_name="content_objects")
    op.drop_index(op.f("ix_content_objects_owner_user_id"), table_name="content_objects")
    op.drop_index(op.f("ix_content_objects_media_type"), table_name="content_objects")
    op.drop_index(op.f("ix_content_objects_kind"), table_name="content_objects")
    op.drop_index(op.f("ix_content_objects_created_at"), table_name="content_objects")
    op.drop_index(op.f("ix_content_objects_category_id"), table_name="content_objects")
    op.drop_table("content_objects")
    op.drop_index(op.f("ix_content_tags_owner_user_id"), table_name="content_tags")
    op.drop_table("content_tags")
    op.drop_index(op.f("ix_content_categories_parent_id"), table_name="content_categories")
    op.drop_index(op.f("ix_content_categories_owner_user_id"), table_name="content_categories")
    op.drop_table("content_categories")
