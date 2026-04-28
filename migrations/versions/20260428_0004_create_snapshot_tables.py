"""create snapshot tables

Revision ID: 20260428_0004
Revises: 20260424_0003
Create Date: 2026-04-28 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260428_0004"
down_revision = "20260424_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "snapshot_user_settings",
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("archive_as_screenshot", sa.Boolean(), nullable=True),
        sa.Column("archive_as_webpage_html", sa.Boolean(), nullable=True),
        sa.Column("archive_as_pdf", sa.Boolean(), nullable=True),
        sa.Column("archive_as_markdown", sa.Boolean(), nullable=True),
        sa.Column("archive_as_archive_org", sa.Boolean(), nullable=True),
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
        "snapshot_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("content_object_id", sa.String(length=36), nullable=False),
        sa.Column("source_asset_id", sa.String(length=36), nullable=True),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint(
            "content_object_id",
            "source_asset_id",
            "job_type",
            name="uq_snapshot_jobs_object_asset_type",
        ),
    )
    op.create_index(
        op.f("ix_snapshot_jobs_content_object_id"), "snapshot_jobs", ["content_object_id"]
    )
    op.create_index(op.f("ix_snapshot_jobs_job_type"), "snapshot_jobs", ["job_type"])
    op.create_index(op.f("ix_snapshot_jobs_owner_user_id"), "snapshot_jobs", ["owner_user_id"])
    op.create_index(op.f("ix_snapshot_jobs_source_asset_id"), "snapshot_jobs", ["source_asset_id"])
    op.create_index(op.f("ix_snapshot_jobs_status"), "snapshot_jobs", ["status"])

    op.create_table(
        "snapshot_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("content_object_id", sa.String(length=36), nullable=False),
        sa.Column("source_asset_id", sa.String(length=36), nullable=True),
        sa.Column("artifact_type", sa.String(length=32), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.String(length=2048), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
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
            "content_object_id",
            "source_asset_id",
            "artifact_type",
            name="uq_snapshot_artifacts_object_asset_type",
        ),
    )
    op.create_index(
        op.f("ix_snapshot_artifacts_artifact_type"),
        "snapshot_artifacts",
        ["artifact_type"],
    )
    op.create_index(
        op.f("ix_snapshot_artifacts_content_object_id"),
        "snapshot_artifacts",
        ["content_object_id"],
    )
    op.create_index(
        op.f("ix_snapshot_artifacts_owner_user_id"),
        "snapshot_artifacts",
        ["owner_user_id"],
    )
    op.create_index(
        op.f("ix_snapshot_artifacts_source_asset_id"),
        "snapshot_artifacts",
        ["source_asset_id"],
    )
    op.create_index(op.f("ix_snapshot_artifacts_status"), "snapshot_artifacts", ["status"])


def downgrade() -> None:
    op.drop_index(op.f("ix_snapshot_artifacts_status"), table_name="snapshot_artifacts")
    op.drop_index(op.f("ix_snapshot_artifacts_source_asset_id"), table_name="snapshot_artifacts")
    op.drop_index(op.f("ix_snapshot_artifacts_owner_user_id"), table_name="snapshot_artifacts")
    op.drop_index(op.f("ix_snapshot_artifacts_content_object_id"), table_name="snapshot_artifacts")
    op.drop_index(op.f("ix_snapshot_artifacts_artifact_type"), table_name="snapshot_artifacts")
    op.drop_table("snapshot_artifacts")

    op.drop_index(op.f("ix_snapshot_jobs_status"), table_name="snapshot_jobs")
    op.drop_index(op.f("ix_snapshot_jobs_source_asset_id"), table_name="snapshot_jobs")
    op.drop_index(op.f("ix_snapshot_jobs_owner_user_id"), table_name="snapshot_jobs")
    op.drop_index(op.f("ix_snapshot_jobs_job_type"), table_name="snapshot_jobs")
    op.drop_index(op.f("ix_snapshot_jobs_content_object_id"), table_name="snapshot_jobs")
    op.drop_table("snapshot_jobs")

    op.drop_table("snapshot_user_settings")
