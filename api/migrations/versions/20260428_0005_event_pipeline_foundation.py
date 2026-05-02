"""add event pipeline foundation

Revision ID: 20260428_0005
Revises: 20260428_0004
Create Date: 2026-04-28 18:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260428_0005"
down_revision = "20260428_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "storage_objects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_entity_type", sa.String(length=128), nullable=False),
        sa.Column("owner_entity_id", sa.String(length=36), nullable=False),
        sa.Column("storage_backend", sa.String(length=32), nullable=False),
        sa.Column("bucket", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=2048), nullable=False),
        sa.Column("storage_ref", sa.String(length=2300), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_storage_objects")),
    )
    op.create_index(
        op.f("ix_storage_objects_owner_entity_type"), "storage_objects", ["owner_entity_type"]
    )
    op.create_index(
        op.f("ix_storage_objects_owner_entity_id"), "storage_objects", ["owner_entity_id"]
    )
    op.create_index(
        op.f("ix_storage_objects_storage_backend"), "storage_objects", ["storage_backend"]
    )
    op.create_index(
        op.f("ix_storage_objects_storage_key"), "storage_objects", ["storage_key"], unique=True
    )

    op.create_table(
        "event_outbox",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("event_name", sa.String(length=128), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("exchange_name", sa.String(length=128), nullable=False),
        sa.Column("routing_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_outbox")),
    )
    op.create_index(op.f("ix_event_outbox_event_id"), "event_outbox", ["event_id"], unique=True)
    op.create_index(op.f("ix_event_outbox_event_name"), "event_outbox", ["event_name"])
    op.create_index(op.f("ix_event_outbox_correlation_id"), "event_outbox", ["correlation_id"])
    op.create_index(op.f("ix_event_outbox_user_id"), "event_outbox", ["user_id"])
    op.create_index(op.f("ix_event_outbox_entity_id"), "event_outbox", ["entity_id"])
    op.create_index(op.f("ix_event_outbox_routing_key"), "event_outbox", ["routing_key"])
    op.create_index(op.f("ix_event_outbox_status"), "event_outbox", ["status"])

    op.create_table(
        "processed_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("consumer_name", sa.String(length=128), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processed_events")),
        sa.UniqueConstraint(
            "event_id",
            "consumer_name",
            name="uq_processed_events_event_consumer",
        ),
    )
    op.create_index(op.f("ix_processed_events_event_id"), "processed_events", ["event_id"])
    op.create_index(
        op.f("ix_processed_events_consumer_name"), "processed_events", ["consumer_name"]
    )

    for table_name in ("content_assets", "content_file_uploads", "snapshot_artifacts"):
        op.add_column(table_name, sa.Column("storage_backend", sa.String(length=32), nullable=True))
        op.add_column(table_name, sa.Column("bucket", sa.String(length=255), nullable=True))
        op.add_column(table_name, sa.Column("storage_key", sa.String(length=2048), nullable=True))
        op.add_column(table_name, sa.Column("storage_ref", sa.String(length=2300), nullable=True))
        op.add_column(table_name, sa.Column("checksum", sa.String(length=128), nullable=True))

    op.add_column(
        "snapshot_jobs", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3")
    )
    op.add_column("snapshot_jobs", sa.Column("correlation_id", sa.String(length=36), nullable=True))
    op.add_column(
        "snapshot_jobs", sa.Column("source_event_id", sa.String(length=36), nullable=True)
    )
    op.add_column("snapshot_jobs", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column(
        "snapshot_jobs", sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}")
    )
    op.add_column(
        "snapshot_jobs", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(op.f("ix_snapshot_jobs_correlation_id"), "snapshot_jobs", ["correlation_id"])
    op.create_index(op.f("ix_snapshot_jobs_source_event_id"), "snapshot_jobs", ["source_event_id"])
    op.alter_column("snapshot_jobs", "max_attempts", server_default=None)
    op.alter_column("snapshot_jobs", "metadata", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_snapshot_jobs_source_event_id"), table_name="snapshot_jobs")
    op.drop_index(op.f("ix_snapshot_jobs_correlation_id"), table_name="snapshot_jobs")
    op.drop_column("snapshot_jobs", "started_at")
    op.drop_column("snapshot_jobs", "metadata")
    op.drop_column("snapshot_jobs", "last_error")
    op.drop_column("snapshot_jobs", "source_event_id")
    op.drop_column("snapshot_jobs", "correlation_id")
    op.drop_column("snapshot_jobs", "max_attempts")

    for table_name in ("snapshot_artifacts", "content_file_uploads", "content_assets"):
        op.drop_column(table_name, "checksum")
        op.drop_column(table_name, "storage_ref")
        op.drop_column(table_name, "storage_key")
        op.drop_column(table_name, "bucket")
        op.drop_column(table_name, "storage_backend")

    op.drop_index(op.f("ix_processed_events_consumer_name"), table_name="processed_events")
    op.drop_index(op.f("ix_processed_events_event_id"), table_name="processed_events")
    op.drop_table("processed_events")

    op.drop_index(op.f("ix_event_outbox_status"), table_name="event_outbox")
    op.drop_index(op.f("ix_event_outbox_routing_key"), table_name="event_outbox")
    op.drop_index(op.f("ix_event_outbox_entity_id"), table_name="event_outbox")
    op.drop_index(op.f("ix_event_outbox_user_id"), table_name="event_outbox")
    op.drop_index(op.f("ix_event_outbox_correlation_id"), table_name="event_outbox")
    op.drop_index(op.f("ix_event_outbox_event_name"), table_name="event_outbox")
    op.drop_index(op.f("ix_event_outbox_event_id"), table_name="event_outbox")
    op.drop_table("event_outbox")

    op.drop_index(op.f("ix_storage_objects_storage_key"), table_name="storage_objects")
    op.drop_index(op.f("ix_storage_objects_storage_backend"), table_name="storage_objects")
    op.drop_index(op.f("ix_storage_objects_owner_entity_id"), table_name="storage_objects")
    op.drop_index(op.f("ix_storage_objects_owner_entity_type"), table_name="storage_objects")
    op.drop_table("storage_objects")
