"""Baseline schema.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-06

Two values are baked into the schema from settings at migration time:
AI_EMBEDDING_DIMENSIONS (halfvec column) and SEARCH_FTS_CONFIG (generated tsvector column).
Job tables get NOTIFY triggers so workers wake up instantly (channel `seyvix_jobs`).
"""

from __future__ import annotations

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings

settings = get_settings()
EMBEDDING_DIMENSIONS = settings.ai_embedding_dimensions
FTS_CONFIG = settings.search_fts_config
JOB_TABLES = (
    "event_deliveries",
    "snapshot_jobs",
    "tagging_jobs",
    "taxonomy_classification_jobs",
    "vectorization_jobs",
)
NOTIFY_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION seyvix_notify_job() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status = 'pending' THEN
        PERFORM pg_notify('seyvix_jobs', TG_TABLE_NAME);
    END IF;
    RETURN NULL;
END
$$;
"""


# revision identifiers, used by Alembic.
revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "access_grants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_by_telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "telegram_user_id IS NOT NULL OR username IS NOT NULL",
            name=op.f("ck_access_grants_ck_access_grants_identity"),
        ),
        sa.CheckConstraint(
            "username = lower(username)",
            name=op.f("ck_access_grants_ck_access_grants_username_lower"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_access_grants")),
        sa.UniqueConstraint("telegram_user_id", name=op.f("uq_access_grants_telegram_user_id")),
        sa.UniqueConstraint("username", name=op.f("uq_access_grants_username")),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
    )
    op.create_index(op.f("ix_events_created_at"), "events", ["created_at"], unique=False)
    op.create_table(
        "taxonomy_templates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_taxonomy_templates")),
        sa.UniqueConstraint("slug", name="uq_taxonomy_templates_slug"),
    )
    op.create_index(
        op.f("ix_taxonomy_templates_is_active"), "taxonomy_templates", ["is_active"], unique=False
    )
    op.create_index(
        op.f("ix_taxonomy_templates_slug"), "taxonomy_templates", ["slug"], unique=False
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("telegram_id", sa.String(length=64), nullable=False),
        sa.Column("telegram_username", sa.String(length=255), nullable=True),
        sa.Column("telegram_photo_url", sa.String(length=2048), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_telegram_id"), "users", ["telegram_id"], unique=True)
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("modules", sa.String(length=255), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("loops", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("worker_id", name=op.f("pk_worker_heartbeats")),
    )
    op.create_index(
        op.f("ix_worker_heartbeats_last_seen_at"),
        "worker_heartbeats",
        ["last_seen_at"],
        unique=False,
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=64), nullable=False),
        sa.Column("previous_refresh_token_hash", sa.String(length=64), nullable=True),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auth_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
        sa.UniqueConstraint("refresh_token_hash", name=op.f("uq_auth_sessions_refresh_token_hash")),
    )
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"], unique=False)
    op.create_index(
        op.f("ix_auth_sessions_previous_refresh_token_hash"),
        "auth_sessions",
        ["previous_refresh_token_hash"],
        unique=False,
    )
    op.create_index(op.f("ix_auth_sessions_user_id"), "auth_sessions", ["user_id"], unique=False)
    op.create_table(
        "content_file_uploads",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("source_filename", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("checksum", sa.String(length=80), nullable=True),
        sa.Column("image_width", sa.Integer(), nullable=True),
        sa.Column("image_height", sa.Integer(), nullable=True),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_content_file_uploads_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_content_file_uploads")),
    )
    op.create_index(
        op.f("ix_content_file_uploads_expires_at"),
        "content_file_uploads",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_file_uploads_owner_user_id"),
        "content_file_uploads",
        ["owner_user_id"],
        unique=False,
    )
    op.create_table(
        "content_objects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("media_type", sa.String(length=32), nullable=True),
        sa.Column("source_filename", sa.String(length=2048), nullable=True),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("is_favorite", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delete_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
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
        "ix_content_objects_owner_changed",
        "content_objects",
        ["owner_user_id", "changed_at"],
        unique=False,
    )
    op.create_index(
        "ix_content_objects_owner_live_created",
        "content_objects",
        ["owner_user_id", sa.literal_column("created_at DESC")],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_content_objects_owner_live_sort",
        "content_objects",
        ["owner_user_id", "sort_order"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_content_objects_owner_trash",
        "content_objects",
        ["owner_user_id", "deleted_at"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )
    op.create_index(
        "ix_content_objects_trash_purge",
        "content_objects",
        ["delete_after"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )
    op.create_table(
        "content_tombstones",
        sa.Column("content_object_id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_content_tombstones_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("content_object_id", name=op.f("pk_content_tombstones")),
    )
    op.create_index(
        "ix_content_tombstones_owner_deleted",
        "content_tombstones",
        ["owner_user_id", "deleted_at"],
        unique=False,
    )
    op.create_table(
        "event_deliveries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("consumer", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name=op.f("fk_event_deliveries_event_id_events"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_deliveries")),
        sa.UniqueConstraint("event_id", "consumer", name=op.f("uq_event_deliveries_event_id")),
        info={"notify_trigger_registered": True},
    )
    op.create_index(
        "ix_event_deliveries_claim",
        "event_deliveries",
        [sa.literal_column("priority DESC"), "run_after"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_event_deliveries_consumer_status",
        "event_deliveries",
        ["consumer", "status"],
        unique=False,
    )
    op.create_index(
        "ix_event_deliveries_lease",
        "event_deliveries",
        ["locked_at"],
        unique=False,
        postgresql_where=sa.text("status = 'processing'"),
    )
    op.create_table(
        "snapshot_user_settings",
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("archive_as_screenshot", sa.Boolean(), nullable=True),
        sa.Column("archive_as_webpage_html", sa.Boolean(), nullable=True),
        sa.Column("archive_as_pdf", sa.Boolean(), nullable=True),
        sa.Column("archive_as_markdown", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_snapshot_user_settings_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("owner_user_id", name=op.f("pk_snapshot_user_settings")),
    )
    op.create_table(
        "tags",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tag_kind", sa.String(length=64), nullable=True),
        sa.Column("aliases", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by_type", sa.String(length=32), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_tags_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_tags_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tags")),
    )
    op.create_index("ix_tags_aliases", "tags", ["aliases"], unique=False, postgresql_using="gin")
    op.create_index(
        op.f("ix_tags_created_by_user_id"), "tags", ["created_by_user_id"], unique=False
    )
    op.create_index(
        "ix_tags_owner_user_id_is_archived", "tags", ["owner_user_id", "is_archived"], unique=False
    )
    op.create_index("uq_tags_owner_user_id_slug", "tags", ["owner_user_id", "slug"], unique=True)
    op.create_table(
        "taxonomy_categories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("is_archived", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "name <> ''", name=op.f("ck_taxonomy_categories_taxonomy_categories_name_not_empty")
        ),
        sa.CheckConstraint(
            "path <> ''", name=op.f("ck_taxonomy_categories_taxonomy_categories_path_not_empty")
        ),
        sa.CheckConstraint(
            "slug <> ''", name=op.f("ck_taxonomy_categories_taxonomy_categories_slug_not_empty")
        ),
        sa.CheckConstraint(
            "depth >= 0", name=op.f("ck_taxonomy_categories_taxonomy_categories_depth_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_taxonomy_categories_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["taxonomy_categories.id"],
            name=op.f("fk_taxonomy_categories_parent_id_taxonomy_categories"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_taxonomy_categories")),
        sa.UniqueConstraint(
            "owner_user_id", "parent_id", "slug", name="uq_taxonomy_categories_owner_parent_slug"
        ),
        sa.UniqueConstraint("owner_user_id", "path", name="uq_taxonomy_categories_owner_path"),
    )
    op.create_index(
        op.f("ix_taxonomy_categories_is_archived"),
        "taxonomy_categories",
        ["is_archived"],
        unique=False,
    )
    op.create_index(
        op.f("ix_taxonomy_categories_owner_user_id"),
        "taxonomy_categories",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_taxonomy_categories_parent_id"), "taxonomy_categories", ["parent_id"], unique=False
    )
    op.create_index(
        op.f("ix_taxonomy_categories_sort_order"),
        "taxonomy_categories",
        ["sort_order"],
        unique=False,
    )
    op.create_index(
        op.f("ix_taxonomy_categories_source"), "taxonomy_categories", ["source"], unique=False
    )
    op.create_index(
        "uq_taxonomy_categories_owner_root_slug",
        "taxonomy_categories",
        ["owner_user_id", "slug"],
        unique=True,
        postgresql_where=sa.text("parent_id IS NULL"),
    )
    op.create_table(
        "taxonomy_template_categories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("template_id", sa.String(length=36), nullable=False),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("profile_summary", sa.Text(), nullable=True),
        sa.Column("profile_keywords", sa.JSON(), nullable=False),
        sa.Column("profile_positive_examples", sa.JSON(), nullable=False),
        sa.Column("profile_negative_examples", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["taxonomy_template_categories.id"],
            name=op.f("fk_taxonomy_template_categories_parent_id_taxonomy_template_categories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["taxonomy_templates.id"],
            name=op.f("fk_taxonomy_template_categories_template_id_taxonomy_templates"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_taxonomy_template_categories")),
        sa.UniqueConstraint("template_id", "path", name="uq_taxonomy_template_categories_path"),
    )
    op.create_index(
        op.f("ix_taxonomy_template_categories_parent_id"),
        "taxonomy_template_categories",
        ["parent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_taxonomy_template_categories_template_id"),
        "taxonomy_template_categories",
        ["template_id"],
        unique=False,
    )
    op.create_table(
        "taxonomy_user_settings",
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("category_profile_editing_enabled", sa.Boolean(), nullable=False),
        sa.Column("trash_enabled", sa.Boolean(), nullable=False),
        sa.Column("trash_retention_days", sa.Integer(), nullable=False),
        sa.Column("tags_auto_apply_mode", sa.String(length=32), nullable=False),
        sa.Column("taxonomy_auto_apply_mode", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_taxonomy_user_settings_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("owner_user_id", name=op.f("pk_taxonomy_user_settings")),
    )
    op.create_table(
        "vectorization_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
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
        sa.UniqueConstraint(
            "owner_user_id",
            "source",
            "source_type",
            "source_id",
            name="uq_vectorization_jobs_scope",
        ),
        info={"notify_trigger_registered": True},
    )
    op.create_index(
        "ix_vectorization_jobs_claim",
        "vectorization_jobs",
        [sa.literal_column("priority DESC"), "run_after"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_vectorization_jobs_lease",
        "vectorization_jobs",
        ["locked_at"],
        unique=False,
        postgresql_where=sa.text("status = 'processing'"),
    )
    op.create_table(
        "vectorization_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("needs_embedding", sa.Boolean(), nullable=False),
        sa.Column("embedding_model", sa.String(length=255), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
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
            "source",
            "source_type",
            "source_id",
            name="uq_vectorization_sources_scope",
        ),
    )
    op.create_index(
        "ix_vectorization_sources_needs_embedding",
        "vectorization_sources",
        ["updated_at"],
        unique=False,
        postgresql_where=sa.text("needs_embedding"),
    )
    op.create_table(
        "classification_feedback",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("content_object_id", sa.String(length=36), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("previous_target_id", sa.String(length=36), nullable=True),
        sa.Column("new_target_id", sa.String(length=36), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action in ('accepted', 'rejected', 'changed', 'manually_assigned', 'removed')",
            name=op.f("ck_classification_feedback_ck_classification_feedback_action"),
        ),
        sa.CheckConstraint(
            "target_type in ('tag', 'taxonomy')",
            name=op.f("ck_classification_feedback_ck_classification_feedback_target_type"),
        ),
        sa.ForeignKeyConstraint(
            ["content_object_id"],
            ["content_objects.id"],
            name=op.f("fk_classification_feedback_content_object_id_content_objects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_classification_feedback_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_classification_feedback")),
    )
    op.create_index(
        op.f("ix_classification_feedback_content_object_id"),
        "classification_feedback",
        ["content_object_id"],
        unique=False,
    )
    op.create_index(
        "ix_classification_feedback_owner_content",
        "classification_feedback",
        ["owner_user_id", "content_object_id"],
        unique=False,
    )
    op.create_index(
        "ix_classification_feedback_owner_target",
        "classification_feedback",
        ["owner_user_id", "target_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_classification_feedback_owner_user_id"),
        "classification_feedback",
        ["owner_user_id"],
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
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("checksum", sa.String(length=80), nullable=True),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column("image_width", sa.Integer(), nullable=True),
        sa.Column("image_height", sa.Integer(), nullable=True),
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
    op.create_index(
        "ix_content_assets_storage_key_prefix",
        "content_assets",
        ["storage_key"],
        unique=False,
        postgresql_ops={"storage_key": "varchar_pattern_ops"},
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
            "content_object_id", name="uq_content_collection_items_content_object_id"
        ),
    )
    op.create_index(
        "ix_content_collection_items_collection_position",
        "content_collection_items",
        ["collection_id", "position"],
        unique=False,
    )
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
            "content_object_id", name=op.f("pk_content_link_snapshot_decisions")
        ),
    )
    op.create_index(
        op.f("ix_content_link_snapshot_decisions_owner_user_id"),
        "content_link_snapshot_decisions",
        ["owner_user_id"],
        unique=False,
    )
    op.create_table(
        "content_tag_assignments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("content_object_id", sa.String(length=36), nullable=False),
        sa.Column("tag_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("assigned_by_type", sa.String(length=32), nullable=False),
        sa.Column("assigned_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status in ('suggested', 'accepted', 'rejected', 'removed')",
            name=op.f("ck_content_tag_assignments_status"),
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by_user_id"],
            ["users.id"],
            name=op.f("fk_content_tag_assignments_assigned_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["content_object_id"],
            ["content_objects.id"],
            name=op.f("fk_content_tag_assignments_content_object_id_content_objects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_content_tag_assignments_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["tags.id"],
            name=op.f("fk_content_tag_assignments_tag_id_tags"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_content_tag_assignments")),
    )
    op.create_index(
        op.f("ix_content_tag_assignments_assigned_by_user_id"),
        "content_tag_assignments",
        ["assigned_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_tag_assignments_content_object_id"),
        "content_tag_assignments",
        ["content_object_id"],
        unique=False,
    )
    op.create_index(
        "ix_content_tag_assignments_owner_content",
        "content_tag_assignments",
        ["owner_user_id", "content_object_id"],
        unique=False,
    )
    op.create_index(
        "ix_content_tag_assignments_owner_status",
        "content_tag_assignments",
        ["owner_user_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_content_tag_assignments_owner_tag",
        "content_tag_assignments",
        ["owner_user_id", "tag_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_tag_assignments_tag_id"),
        "content_tag_assignments",
        ["tag_id"],
        unique=False,
    )
    op.create_index(
        "uq_content_tag_assignments_active",
        "content_tag_assignments",
        ["owner_user_id", "content_object_id", "tag_id"],
        unique=True,
        postgresql_where=sa.text("status in ('suggested', 'accepted')"),
    )
    op.create_table(
        "tagging_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("content_object_id", sa.String(length=36), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("rerun_requested", sa.Boolean(), nullable=False),
        sa.Column("source_event_id", sa.String(length=36), nullable=True),
        sa.Column("correlation_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status in ('pending', 'processing', 'succeeded', 'failed', 'cancelled')",
            name=op.f("ck_tagging_jobs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["content_object_id"],
            ["content_objects.id"],
            name=op.f("fk_tagging_jobs_content_object_id_content_objects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_tagging_jobs_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tagging_jobs")),
        sa.UniqueConstraint(
            "content_object_id", "job_type", name="uq_tagging_jobs_content_object_id_job_type"
        ),
        info={"notify_trigger_registered": True},
    )
    op.create_index(
        "ix_tagging_jobs_claim",
        "tagging_jobs",
        [sa.literal_column("priority DESC"), "run_after"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_tagging_jobs_lease",
        "tagging_jobs",
        ["locked_at"],
        unique=False,
        postgresql_where=sa.text("status = 'processing'"),
    )
    op.create_index(
        "ix_tagging_jobs_owner_status", "tagging_jobs", ["owner_user_id", "status"], unique=False
    )
    op.create_table(
        "taxonomy_category_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("category_id", sa.String(length=36), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("positive_examples", sa.JSON(), nullable=False),
        sa.Column("negative_examples", sa.JSON(), nullable=False),
        sa.Column("profile_source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["taxonomy_categories.id"],
            name=op.f("fk_taxonomy_category_profiles_category_id_taxonomy_categories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_taxonomy_category_profiles")),
        sa.UniqueConstraint("category_id", name="uq_taxonomy_profiles_category_id"),
    )
    op.create_index(
        op.f("ix_taxonomy_category_profiles_category_id"),
        "taxonomy_category_profiles",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_taxonomy_category_profiles_profile_source"),
        "taxonomy_category_profiles",
        ["profile_source"],
        unique=False,
    )
    op.create_table(
        "taxonomy_content_assignments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("content_object_id", sa.String(length=36), nullable=False),
        sa.Column("category_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("assigned_by", sa.String(length=32), nullable=False),
        sa.Column("alternatives", sa.JSON(), nullable=False),
        sa.Column("category_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("category_path_snapshot", sa.String(length=1024), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status in ('proposed', 'accepted', 'rejected', 'overridden')",
            name=op.f("ck_taxonomy_content_assignments_ck_taxonomy_assignments_status"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["taxonomy_categories.id"],
            name=op.f("fk_taxonomy_content_assignments_category_id_taxonomy_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["content_object_id"],
            ["content_objects.id"],
            name=op.f("fk_taxonomy_content_assignments_content_object_id_content_objects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_taxonomy_content_assignments_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_taxonomy_content_assignments")),
    )
    op.create_index(
        "ix_taxonomy_assignments_owner_category",
        "taxonomy_content_assignments",
        ["owner_user_id", "category_id"],
        unique=False,
    )
    op.create_index(
        "ix_taxonomy_assignments_owner_content",
        "taxonomy_content_assignments",
        ["owner_user_id", "content_object_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_taxonomy_content_assignments_assigned_by"),
        "taxonomy_content_assignments",
        ["assigned_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_taxonomy_content_assignments_category_id"),
        "taxonomy_content_assignments",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_taxonomy_content_assignments_content_object_id"),
        "taxonomy_content_assignments",
        ["content_object_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_taxonomy_content_assignments_is_current"),
        "taxonomy_content_assignments",
        ["is_current"],
        unique=False,
    )
    op.create_index(
        op.f("ix_taxonomy_content_assignments_owner_user_id"),
        "taxonomy_content_assignments",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_taxonomy_content_assignments_status"),
        "taxonomy_content_assignments",
        ["status"],
        unique=False,
    )
    op.create_index(
        "uq_taxonomy_assignments_current_content",
        "taxonomy_content_assignments",
        ["owner_user_id", "content_object_id"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
    )
    op.create_table(
        "telegram_bot_states",
        sa.Column("telegram_user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("active_collection_id", sa.String(length=36), nullable=True),
        sa.Column("manual_collection_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("manual_collection_last_item_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("manual_collection_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "mode IN ('auto', 'separate', 'manual_collection')",
            name=op.f("ck_telegram_bot_states_ck_telegram_bot_states_mode"),
        ),
        sa.ForeignKeyConstraint(
            ["active_collection_id"],
            ["content_objects.id"],
            name=op.f("fk_telegram_bot_states_active_collection_id_content_objects"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("telegram_user_id", name=op.f("pk_telegram_bot_states")),
    )
    op.create_index(
        op.f("ix_telegram_bot_states_active_collection_id"),
        "telegram_bot_states",
        ["active_collection_id"],
        unique=False,
    )
    op.create_index(
        "ix_telegram_bot_states_reminder_due",
        "telegram_bot_states",
        ["manual_collection_last_item_at"],
        unique=False,
        postgresql_where=sa.text(
            "mode = 'manual_collection' AND active_collection_id IS NOT NULL AND manual_collection_reminder_sent_at IS NULL"
        ),
    )
    op.create_table(
        "vectorization_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_record_id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(length=32), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(f"to_tsvector('{FTS_CONFIG}'::regconfig, text)", persisted=True),
            nullable=False,
        ),
        sa.Column(
            "embedding", pgvector.sqlalchemy.HALFVEC(dim=EMBEDDING_DIMENSIONS), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["vectorization_sources.id"],
            name=op.f("fk_vectorization_chunks_source_record_id_vectorization_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vectorization_chunks")),
        sa.UniqueConstraint(
            "source_record_id", "chunk_index", name="uq_vectorization_chunks_source_index"
        ),
    )
    op.create_index(
        "ix_vectorization_chunks_embedding_hnsw",
        "vectorization_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "halfvec_cosine_ops"},
    )
    op.create_index(
        "ix_vectorization_chunks_owner", "vectorization_chunks", ["owner_user_id"], unique=False
    )
    op.create_index(
        "ix_vectorization_chunks_search_vector",
        "vectorization_chunks",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )
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
    op.create_index(
        op.f("ix_content_sources_content_asset_id"),
        "content_sources",
        ["content_asset_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_sources_content_object_id"),
        "content_sources",
        ["content_object_id"],
        unique=False,
    )
    op.create_index(
        "ix_content_sources_owner_provider",
        "content_sources",
        ["owner_user_id", "provider"],
        unique=False,
    )
    op.create_table(
        "snapshot_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("content_object_id", sa.String(length=36), nullable=False),
        sa.Column("source_asset_id", sa.String(length=36), nullable=False),
        sa.Column("artifact_type", sa.String(length=32), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=True),
        sa.Column("checksum", sa.String(length=80), nullable=True),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["content_object_id"],
            ["content_objects.id"],
            name=op.f("fk_snapshot_artifacts_content_object_id_content_objects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_snapshot_artifacts_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_asset_id"],
            ["content_assets.id"],
            name=op.f("fk_snapshot_artifacts_source_asset_id_content_assets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_snapshot_artifacts")),
        sa.UniqueConstraint(
            "source_asset_id", "artifact_type", name="uq_snapshot_artifacts_asset_type"
        ),
    )
    op.create_index(
        op.f("ix_snapshot_artifacts_content_object_id"),
        "snapshot_artifacts",
        ["content_object_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_snapshot_artifacts_owner_user_id"),
        "snapshot_artifacts",
        ["owner_user_id"],
        unique=False,
    )
    op.create_table(
        "snapshot_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("content_object_id", sa.String(length=36), nullable=False),
        sa.Column("source_asset_id", sa.String(length=36), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=36), nullable=True),
        sa.Column("source_event_id", sa.String(length=36), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["content_object_id"],
            ["content_objects.id"],
            name=op.f("fk_snapshot_jobs_content_object_id_content_objects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_snapshot_jobs_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_asset_id"],
            ["content_assets.id"],
            name=op.f("fk_snapshot_jobs_source_asset_id_content_assets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_snapshot_jobs")),
        sa.UniqueConstraint("source_asset_id", "job_type", name="uq_snapshot_jobs_asset_type"),
        info={"notify_trigger_registered": True},
    )
    op.create_index(
        "ix_snapshot_jobs_claim",
        "snapshot_jobs",
        [sa.literal_column("priority DESC"), "run_after"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        op.f("ix_snapshot_jobs_content_object_id"),
        "snapshot_jobs",
        ["content_object_id"],
        unique=False,
    )
    op.create_index(
        "ix_snapshot_jobs_lease",
        "snapshot_jobs",
        ["locked_at"],
        unique=False,
        postgresql_where=sa.text("status = 'processing'"),
    )
    op.create_index(
        op.f("ix_snapshot_jobs_owner_user_id"), "snapshot_jobs", ["owner_user_id"], unique=False
    )
    op.create_table(
        "taxonomy_classification_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("content_object_id", sa.String(length=36), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("rerun_requested", sa.Boolean(), nullable=False),
        sa.Column("source_event_id", sa.String(length=36), nullable=True),
        sa.Column("correlation_id", sa.String(length=36), nullable=True),
        sa.Column("assignment_id", sa.String(length=36), nullable=True),
        sa.Column("result_status", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status in ('pending', 'processing', 'succeeded', 'failed', 'cancelled')",
            name=op.f("ck_taxonomy_classification_jobs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["taxonomy_content_assignments.id"],
            name=op.f("fk_taxonomy_classification_jobs_assignment_id_taxonomy_content_assignments"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["content_object_id"],
            ["content_objects.id"],
            name=op.f("fk_taxonomy_classification_jobs_content_object_id_content_objects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_taxonomy_classification_jobs_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_taxonomy_classification_jobs")),
        sa.UniqueConstraint(
            "content_object_id",
            "job_type",
            name="uq_taxonomy_classification_jobs_content_object_id_job_type",
        ),
        info={"notify_trigger_registered": True},
    )
    op.create_index(
        "ix_taxonomy_classification_jobs_claim",
        "taxonomy_classification_jobs",
        [sa.literal_column("priority DESC"), "run_after"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_taxonomy_classification_jobs_lease",
        "taxonomy_classification_jobs",
        ["locked_at"],
        unique=False,
        postgresql_where=sa.text("status = 'processing'"),
    )
    op.create_index(
        "ix_taxonomy_classification_jobs_owner_status",
        "taxonomy_classification_jobs",
        ["owner_user_id", "status"],
        unique=False,
    )
    op.execute(NOTIFY_FUNCTION_SQL)
    for table in JOB_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_notify AFTER INSERT OR UPDATE OF status, run_after "
            f"ON {table} FOR EACH ROW EXECUTE FUNCTION seyvix_notify_job()"
        )


def downgrade() -> None:
    op.drop_index(
        "ix_taxonomy_classification_jobs_owner_status", table_name="taxonomy_classification_jobs"
    )
    op.drop_index(
        "ix_taxonomy_classification_jobs_lease",
        table_name="taxonomy_classification_jobs",
        postgresql_where=sa.text("status = 'processing'"),
    )
    op.drop_index(
        "ix_taxonomy_classification_jobs_claim",
        table_name="taxonomy_classification_jobs",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_table("taxonomy_classification_jobs")
    op.drop_index(op.f("ix_snapshot_jobs_owner_user_id"), table_name="snapshot_jobs")
    op.drop_index(
        "ix_snapshot_jobs_lease",
        table_name="snapshot_jobs",
        postgresql_where=sa.text("status = 'processing'"),
    )
    op.drop_index(op.f("ix_snapshot_jobs_content_object_id"), table_name="snapshot_jobs")
    op.drop_index(
        "ix_snapshot_jobs_claim",
        table_name="snapshot_jobs",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_table("snapshot_jobs")
    op.drop_index(op.f("ix_snapshot_artifacts_owner_user_id"), table_name="snapshot_artifacts")
    op.drop_index(op.f("ix_snapshot_artifacts_content_object_id"), table_name="snapshot_artifacts")
    op.drop_table("snapshot_artifacts")
    op.drop_index("ix_content_sources_owner_provider", table_name="content_sources")
    op.drop_index(op.f("ix_content_sources_content_object_id"), table_name="content_sources")
    op.drop_index(op.f("ix_content_sources_content_asset_id"), table_name="content_sources")
    op.drop_table("content_sources")
    op.drop_index(
        "ix_vectorization_chunks_search_vector",
        table_name="vectorization_chunks",
        postgresql_using="gin",
    )
    op.drop_index("ix_vectorization_chunks_owner", table_name="vectorization_chunks")
    op.drop_index(
        "ix_vectorization_chunks_embedding_hnsw",
        table_name="vectorization_chunks",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "halfvec_cosine_ops"},
    )
    op.drop_table("vectorization_chunks")
    op.drop_index(
        "ix_telegram_bot_states_reminder_due",
        table_name="telegram_bot_states",
        postgresql_where=sa.text(
            "mode = 'manual_collection' AND active_collection_id IS NOT NULL AND manual_collection_reminder_sent_at IS NULL"
        ),
    )
    op.drop_index(
        op.f("ix_telegram_bot_states_active_collection_id"), table_name="telegram_bot_states"
    )
    op.drop_table("telegram_bot_states")
    op.drop_index(
        "uq_taxonomy_assignments_current_content",
        table_name="taxonomy_content_assignments",
        postgresql_where=sa.text("is_current = true"),
    )
    op.drop_index(
        op.f("ix_taxonomy_content_assignments_status"), table_name="taxonomy_content_assignments"
    )
    op.drop_index(
        op.f("ix_taxonomy_content_assignments_owner_user_id"),
        table_name="taxonomy_content_assignments",
    )
    op.drop_index(
        op.f("ix_taxonomy_content_assignments_is_current"),
        table_name="taxonomy_content_assignments",
    )
    op.drop_index(
        op.f("ix_taxonomy_content_assignments_content_object_id"),
        table_name="taxonomy_content_assignments",
    )
    op.drop_index(
        op.f("ix_taxonomy_content_assignments_category_id"),
        table_name="taxonomy_content_assignments",
    )
    op.drop_index(
        op.f("ix_taxonomy_content_assignments_assigned_by"),
        table_name="taxonomy_content_assignments",
    )
    op.drop_index(
        "ix_taxonomy_assignments_owner_content", table_name="taxonomy_content_assignments"
    )
    op.drop_index(
        "ix_taxonomy_assignments_owner_category", table_name="taxonomy_content_assignments"
    )
    op.drop_table("taxonomy_content_assignments")
    op.drop_index(
        op.f("ix_taxonomy_category_profiles_profile_source"),
        table_name="taxonomy_category_profiles",
    )
    op.drop_index(
        op.f("ix_taxonomy_category_profiles_category_id"), table_name="taxonomy_category_profiles"
    )
    op.drop_table("taxonomy_category_profiles")
    op.drop_index("ix_tagging_jobs_owner_status", table_name="tagging_jobs")
    op.drop_index(
        "ix_tagging_jobs_lease",
        table_name="tagging_jobs",
        postgresql_where=sa.text("status = 'processing'"),
    )
    op.drop_index(
        "ix_tagging_jobs_claim",
        table_name="tagging_jobs",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_table("tagging_jobs")
    op.drop_index(
        "uq_content_tag_assignments_active",
        table_name="content_tag_assignments",
        postgresql_where=sa.text("status in ('suggested', 'accepted')"),
    )
    op.drop_index(op.f("ix_content_tag_assignments_tag_id"), table_name="content_tag_assignments")
    op.drop_index("ix_content_tag_assignments_owner_tag", table_name="content_tag_assignments")
    op.drop_index("ix_content_tag_assignments_owner_status", table_name="content_tag_assignments")
    op.drop_index("ix_content_tag_assignments_owner_content", table_name="content_tag_assignments")
    op.drop_index(
        op.f("ix_content_tag_assignments_content_object_id"), table_name="content_tag_assignments"
    )
    op.drop_index(
        op.f("ix_content_tag_assignments_assigned_by_user_id"), table_name="content_tag_assignments"
    )
    op.drop_table("content_tag_assignments")
    op.drop_index(
        op.f("ix_content_link_snapshot_decisions_owner_user_id"),
        table_name="content_link_snapshot_decisions",
    )
    op.drop_table("content_link_snapshot_decisions")
    op.drop_index(
        "ix_content_collection_items_collection_position", table_name="content_collection_items"
    )
    op.drop_table("content_collection_items")
    op.drop_index(
        "ix_content_assets_storage_key_prefix",
        table_name="content_assets",
        postgresql_ops={"storage_key": "varchar_pattern_ops"},
    )
    op.drop_index(op.f("ix_content_assets_content_object_id"), table_name="content_assets")
    op.drop_table("content_assets")
    op.drop_index(
        op.f("ix_classification_feedback_owner_user_id"), table_name="classification_feedback"
    )
    op.drop_index("ix_classification_feedback_owner_target", table_name="classification_feedback")
    op.drop_index("ix_classification_feedback_owner_content", table_name="classification_feedback")
    op.drop_index(
        op.f("ix_classification_feedback_content_object_id"), table_name="classification_feedback"
    )
    op.drop_table("classification_feedback")
    op.drop_index(
        "ix_vectorization_sources_needs_embedding",
        table_name="vectorization_sources",
        postgresql_where=sa.text("needs_embedding"),
    )
    op.drop_table("vectorization_sources")
    op.drop_index(
        "ix_vectorization_jobs_lease",
        table_name="vectorization_jobs",
        postgresql_where=sa.text("status = 'processing'"),
    )
    op.drop_index(
        "ix_vectorization_jobs_claim",
        table_name="vectorization_jobs",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_table("vectorization_jobs")
    op.drop_table("taxonomy_user_settings")
    op.drop_index(
        op.f("ix_taxonomy_template_categories_template_id"),
        table_name="taxonomy_template_categories",
    )
    op.drop_index(
        op.f("ix_taxonomy_template_categories_parent_id"), table_name="taxonomy_template_categories"
    )
    op.drop_table("taxonomy_template_categories")
    op.drop_index(
        "uq_taxonomy_categories_owner_root_slug",
        table_name="taxonomy_categories",
        postgresql_where=sa.text("parent_id IS NULL"),
    )
    op.drop_index(op.f("ix_taxonomy_categories_source"), table_name="taxonomy_categories")
    op.drop_index(op.f("ix_taxonomy_categories_sort_order"), table_name="taxonomy_categories")
    op.drop_index(op.f("ix_taxonomy_categories_parent_id"), table_name="taxonomy_categories")
    op.drop_index(op.f("ix_taxonomy_categories_owner_user_id"), table_name="taxonomy_categories")
    op.drop_index(op.f("ix_taxonomy_categories_is_archived"), table_name="taxonomy_categories")
    op.drop_table("taxonomy_categories")
    op.drop_index("uq_tags_owner_user_id_slug", table_name="tags")
    op.drop_index("ix_tags_owner_user_id_is_archived", table_name="tags")
    op.drop_index(op.f("ix_tags_created_by_user_id"), table_name="tags")
    op.drop_index("ix_tags_aliases", table_name="tags", postgresql_using="gin")
    op.drop_table("tags")
    op.drop_table("snapshot_user_settings")
    op.drop_index(
        "ix_event_deliveries_lease",
        table_name="event_deliveries",
        postgresql_where=sa.text("status = 'processing'"),
    )
    op.drop_index("ix_event_deliveries_consumer_status", table_name="event_deliveries")
    op.drop_index(
        "ix_event_deliveries_claim",
        table_name="event_deliveries",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_table("event_deliveries")
    op.drop_index("ix_content_tombstones_owner_deleted", table_name="content_tombstones")
    op.drop_table("content_tombstones")
    op.drop_index(
        "ix_content_objects_trash_purge",
        table_name="content_objects",
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )
    op.drop_index(
        "ix_content_objects_owner_trash",
        table_name="content_objects",
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )
    op.drop_index(
        "ix_content_objects_owner_live_sort",
        table_name="content_objects",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index(
        "ix_content_objects_owner_live_created",
        table_name="content_objects",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index("ix_content_objects_owner_changed", table_name="content_objects")
    op.drop_table("content_objects")
    op.drop_index(op.f("ix_content_file_uploads_owner_user_id"), table_name="content_file_uploads")
    op.drop_index(op.f("ix_content_file_uploads_expires_at"), table_name="content_file_uploads")
    op.drop_table("content_file_uploads")
    op.drop_index(op.f("ix_auth_sessions_user_id"), table_name="auth_sessions")
    op.drop_index(op.f("ix_auth_sessions_previous_refresh_token_hash"), table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index(op.f("ix_worker_heartbeats_last_seen_at"), table_name="worker_heartbeats")
    op.drop_table("worker_heartbeats")
    op.drop_index(op.f("ix_users_telegram_id"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_taxonomy_templates_slug"), table_name="taxonomy_templates")
    op.drop_index(op.f("ix_taxonomy_templates_is_active"), table_name="taxonomy_templates")
    op.drop_table("taxonomy_templates")
    op.drop_index(op.f("ix_events_created_at"), table_name="events")
    op.drop_table("events")
    op.drop_table("access_grants")
    op.execute("DROP FUNCTION IF EXISTS seyvix_notify_job() CASCADE")
