"""create taxonomy classification jobs

Revision ID: 20260501_0009
Revises: 20260430_0008
Create Date: 2026-05-01 09:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260501_0009"
down_revision = "20260430_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "taxonomy_classification_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("content_object_id", sa.String(length=36), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=255), nullable=True),
        sa.Column("source_event_id", sa.String(length=36), nullable=True),
        sa.Column("correlation_id", sa.String(length=36), nullable=True),
        sa.Column("assignment_id", sa.String(length=36), nullable=True),
        sa.Column("result_status", sa.String(length=32), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
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
            "source_event_id",
            name="uq_taxonomy_classification_jobs_source_event_id",
        ),
    )
    op.create_index(
        op.f("ix_taxonomy_classification_jobs_owner_user_id"),
        "taxonomy_classification_jobs",
        ["owner_user_id"],
    )
    op.create_index(
        op.f("ix_taxonomy_classification_jobs_content_object_id"),
        "taxonomy_classification_jobs",
        ["content_object_id"],
    )
    op.create_index(
        op.f("ix_taxonomy_classification_jobs_status"),
        "taxonomy_classification_jobs",
        ["status"],
    )
    op.create_index(
        "ix_taxonomy_classification_jobs_status_run_after_priority",
        "taxonomy_classification_jobs",
        ["status", "run_after", "priority"],
    )
    op.create_index(
        "ix_taxonomy_classification_jobs_owner_content",
        "taxonomy_classification_jobs",
        ["owner_user_id", "content_object_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_taxonomy_classification_jobs_owner_content",
        table_name="taxonomy_classification_jobs",
    )
    op.drop_index(
        "ix_taxonomy_classification_jobs_status_run_after_priority",
        table_name="taxonomy_classification_jobs",
    )
    op.drop_index(
        op.f("ix_taxonomy_classification_jobs_status"),
        table_name="taxonomy_classification_jobs",
    )
    op.drop_index(
        op.f("ix_taxonomy_classification_jobs_content_object_id"),
        table_name="taxonomy_classification_jobs",
    )
    op.drop_index(
        op.f("ix_taxonomy_classification_jobs_owner_user_id"),
        table_name="taxonomy_classification_jobs",
    )
    op.drop_table("taxonomy_classification_jobs")
