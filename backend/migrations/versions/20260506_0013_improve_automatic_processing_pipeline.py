"""improve automatic processing pipeline

Revision ID: 20260506_0013
Revises: 20260503_0012
Create Date: 2026-05-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260506_0013"
down_revision = "20260503_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tags",
        sa.Column("aliases", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "tagging_jobs",
        sa.Column("source_event_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "tagging_jobs",
        sa.Column("correlation_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "tagging_jobs",
        sa.Column("content_updated_at_snapshot", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_tagging_jobs_source_event_id",
        "tagging_jobs",
        ["source_event_id"],
    )
    op.create_check_constraint(
        "ck_content_tag_assignments_status",
        "content_tag_assignments",
        "status in ('suggested', 'accepted', 'rejected', 'removed')",
    )
    op.create_check_constraint(
        "ck_tagging_jobs_status",
        "tagging_jobs",
        "status in ('pending', 'processing', 'succeeded', 'failed', 'cancelled', 'stale')",
    )

    op.add_column(
        "taxonomy_category_profiles",
        sa.Column(
            "profile_source",
            sa.String(length=32),
            nullable=False,
            server_default="template",
        ),
    )
    op.create_index(
        op.f("ix_taxonomy_category_profiles_profile_source"),
        "taxonomy_category_profiles",
        ["profile_source"],
        unique=False,
    )

    op.add_column(
        "taxonomy_user_settings",
        sa.Column(
            "tags_auto_apply_mode",
            sa.String(length=32),
            nullable=False,
            server_default="auto_apply_high_confidence",
        ),
    )
    op.add_column(
        "taxonomy_user_settings",
        sa.Column(
            "taxonomy_auto_apply_mode",
            sa.String(length=32),
            nullable=False,
            server_default="auto_apply_high_confidence",
        ),
    )
    op.add_column(
        "taxonomy_classification_jobs",
        sa.Column("content_updated_at_snapshot", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_taxonomy_assignments_status",
        "taxonomy_content_assignments",
        "status in ('proposed', 'accepted', 'rejected', 'overridden')",
    )
    op.create_check_constraint(
        "ck_taxonomy_classification_jobs_status",
        "taxonomy_classification_jobs",
        "status in ('pending', 'processing', 'succeeded', 'failed', 'cancelled', 'stale')",
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
            name="ck_classification_feedback_action",
        ),
        sa.CheckConstraint(
            "target_type in ('tag', 'taxonomy')",
            name="ck_classification_feedback_target_type",
        ),
        sa.ForeignKeyConstraint(["content_object_id"], ["content_objects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
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


def downgrade() -> None:
    op.drop_index("ix_classification_feedback_owner_target", table_name="classification_feedback")
    op.drop_index("ix_classification_feedback_owner_content", table_name="classification_feedback")
    op.drop_table("classification_feedback")
    op.drop_constraint(
        "ck_taxonomy_classification_jobs_status",
        "taxonomy_classification_jobs",
        type_="check",
    )
    op.drop_constraint(
        "ck_taxonomy_assignments_status",
        "taxonomy_content_assignments",
        type_="check",
    )
    op.drop_column("taxonomy_classification_jobs", "content_updated_at_snapshot")
    op.drop_column("taxonomy_user_settings", "taxonomy_auto_apply_mode")
    op.drop_column("taxonomy_user_settings", "tags_auto_apply_mode")
    op.drop_index(
        op.f("ix_taxonomy_category_profiles_profile_source"),
        table_name="taxonomy_category_profiles",
    )
    op.drop_column("taxonomy_category_profiles", "profile_source")
    op.drop_constraint("ck_tagging_jobs_status", "tagging_jobs", type_="check")
    op.drop_constraint(
        "ck_content_tag_assignments_status",
        "content_tag_assignments",
        type_="check",
    )
    op.drop_constraint("uq_tagging_jobs_source_event_id", "tagging_jobs", type_="unique")
    op.drop_column("tagging_jobs", "content_updated_at_snapshot")
    op.drop_column("tagging_jobs", "correlation_id")
    op.drop_column("tagging_jobs", "source_event_id")
    op.drop_column("tags", "aliases")
