"""create tags tables

Revision ID: 20260430_0008
Revises: 20260429_0007
Create Date: 2026-04-30 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260430_0008"
down_revision = "20260429_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tag_kind", sa.String(length=64), nullable=True),
        sa.Column("created_by_type", sa.String(length=32), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_detail", sa.JSON(), nullable=False),
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
    op.create_index(op.f("ix_tags_owner_user_id"), "tags", ["owner_user_id"])
    op.create_index(op.f("ix_tags_created_by_user_id"), "tags", ["created_by_user_id"])
    op.create_index("uq_tags_owner_user_id_slug", "tags", ["owner_user_id", "slug"], unique=True)
    op.create_index(
        "ix_tags_owner_user_id_is_archived",
        "tags",
        ["owner_user_id", "is_archived"],
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
        sa.Column("source_detail", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
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
        op.f("ix_content_tag_assignments_owner_user_id"),
        "content_tag_assignments",
        ["owner_user_id"],
    )
    op.create_index(
        op.f("ix_content_tag_assignments_content_object_id"),
        "content_tag_assignments",
        ["content_object_id"],
    )
    op.create_index(
        op.f("ix_content_tag_assignments_tag_id"),
        "content_tag_assignments",
        ["tag_id"],
    )
    op.create_index(
        op.f("ix_content_tag_assignments_assigned_by_user_id"),
        "content_tag_assignments",
        ["assigned_by_user_id"],
    )
    op.create_index(
        "ix_content_tag_assignments_owner_content",
        "content_tag_assignments",
        ["owner_user_id", "content_object_id"],
    )
    op.create_index(
        "ix_content_tag_assignments_owner_tag",
        "content_tag_assignments",
        ["owner_user_id", "tag_id"],
    )
    op.create_index(
        "ix_content_tag_assignments_owner_status",
        "content_tag_assignments",
        ["owner_user_id", "status"],
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
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("content_object_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=255), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
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
    )
    op.create_index(op.f("ix_tagging_jobs_owner_user_id"), "tagging_jobs", ["owner_user_id"])
    op.create_index(
        op.f("ix_tagging_jobs_content_object_id"), "tagging_jobs", ["content_object_id"]
    )
    op.create_index(op.f("ix_tagging_jobs_status"), "tagging_jobs", ["status"])
    op.create_index(
        "ix_tagging_jobs_status_run_after_priority",
        "tagging_jobs",
        ["status", "run_after", "priority"],
    )
    op.create_index(
        "ix_tagging_jobs_owner_content",
        "tagging_jobs",
        ["owner_user_id", "content_object_id"],
    )

    # Deprecated compatibility schema: content_tags and content_object_tags remain in place
    # for old deployments, but runtime writes are owned by app.modules.tags after this migration.
    op.execute(
        """
        INSERT INTO tags (
            id, owner_user_id, name, slug, description, tag_kind, created_by_type,
            created_by_user_id, source, source_detail, confidence, is_archived,
            created_at, updated_at
        )
        SELECT
            id, owner_user_id, name, slug, NULL, tag_type, 'migration', NULL,
            'migration', '{}'::json, NULL, false, created_at, created_at
        FROM content_tags
        ON CONFLICT (owner_user_id, slug) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO content_tag_assignments (
            id, owner_user_id, content_object_id, tag_id, status, assigned_by_type,
            assigned_by_user_id, source, source_detail, confidence, reasoning,
            created_at, updated_at
        )
        SELECT
            substr(md5(cot.content_object_id || ':' || cot.tag_id), 1, 8) || '-' ||
            substr(md5(cot.content_object_id || ':' || cot.tag_id), 9, 4) || '-' ||
            substr(md5(cot.content_object_id || ':' || cot.tag_id), 13, 4) || '-' ||
            substr(md5(cot.content_object_id || ':' || cot.tag_id), 17, 4) || '-' ||
            substr(md5(cot.content_object_id || ':' || cot.tag_id), 21, 12),
            co.owner_user_id,
            cot.content_object_id,
            cot.tag_id,
            'accepted',
            'migration',
            NULL,
            'imported',
            '{"legacy_tables":["content_tags","content_object_tags"]}'::json,
            NULL,
            'Migrated from legacy content tag tables.',
            now(),
            now()
        FROM content_object_tags cot
        JOIN content_objects co ON co.id = cot.content_object_id
        JOIN tags t ON t.id = cot.tag_id
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_tagging_jobs_owner_content", table_name="tagging_jobs")
    op.drop_index("ix_tagging_jobs_status_run_after_priority", table_name="tagging_jobs")
    op.drop_index(op.f("ix_tagging_jobs_status"), table_name="tagging_jobs")
    op.drop_index(op.f("ix_tagging_jobs_content_object_id"), table_name="tagging_jobs")
    op.drop_index(op.f("ix_tagging_jobs_owner_user_id"), table_name="tagging_jobs")
    op.drop_table("tagging_jobs")

    op.drop_index("uq_content_tag_assignments_active", table_name="content_tag_assignments")
    op.drop_index("ix_content_tag_assignments_owner_status", table_name="content_tag_assignments")
    op.drop_index("ix_content_tag_assignments_owner_tag", table_name="content_tag_assignments")
    op.drop_index("ix_content_tag_assignments_owner_content", table_name="content_tag_assignments")
    op.drop_index(
        op.f("ix_content_tag_assignments_assigned_by_user_id"),
        table_name="content_tag_assignments",
    )
    op.drop_index(op.f("ix_content_tag_assignments_tag_id"), table_name="content_tag_assignments")
    op.drop_index(
        op.f("ix_content_tag_assignments_content_object_id"),
        table_name="content_tag_assignments",
    )
    op.drop_index(
        op.f("ix_content_tag_assignments_owner_user_id"),
        table_name="content_tag_assignments",
    )
    op.drop_table("content_tag_assignments")

    op.drop_index("ix_tags_owner_user_id_is_archived", table_name="tags")
    op.drop_index("uq_tags_owner_user_id_slug", table_name="tags")
    op.drop_index(op.f("ix_tags_created_by_user_id"), table_name="tags")
    op.drop_index(op.f("ix_tags_owner_user_id"), table_name="tags")
    op.drop_table("tags")
