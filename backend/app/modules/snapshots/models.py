from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.platform.jobs import JobColumnsMixin, job_queue_indexes, utcnow


class SnapshotUserSettings(Base):
    """Per-user overrides of the server snapshot defaults (NULL = inherit)."""

    __tablename__ = "snapshot_user_settings"

    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    archive_as_screenshot: Mapped[bool | None] = mapped_column(nullable=True)
    archive_as_webpage_html: Mapped[bool | None] = mapped_column(nullable=True)
    archive_as_pdf: Mapped[bool | None] = mapped_column(nullable=True)
    archive_as_markdown: Mapped[bool | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SnapshotJob(JobColumnsMixin, Base):
    """One output type (`job_type`) of one source asset.

    The runner claims every due job of an asset together and produces all of them from a
    single pass over the source (one page render for links, one office conversion, ...).
    `source_fingerprint` identifies the source content the job was planned for, so repeated
    `content.object.updated` events only re-run jobs whose source actually changed.
    """

    __tablename__ = "snapshot_jobs"
    __table_args__ = (
        UniqueConstraint("source_asset_id", "job_type", name="uq_snapshot_jobs_asset_type"),
        *job_queue_indexes("snapshot_jobs"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    content_object_id: Mapped[str] = mapped_column(
        ForeignKey("content_objects.id", ondelete="CASCADE"), index=True
    )
    source_asset_id: Mapped[str] = mapped_column(
        ForeignKey("content_assets.id", ondelete="CASCADE")
    )
    job_type: Mapped[str] = mapped_column(String(32))
    source_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    correlation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON(), default=dict)


class SnapshotArtifact(Base):
    """The current output of one type for one source asset.

    File artifacts live in storage under the asset's directory
    (`.../assets/{asset_id}/snapshots/{artifact_type}/{artifact_id}/...`); small text
    artifacts (`thumbnail_text`) are kept inline in `text_content` and have no storage key.
    A re-snapshot replaces the row (new id) and deletes the previous files.
    """

    __tablename__ = "snapshot_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "source_asset_id", "artifact_type", name="uq_snapshot_artifacts_asset_type"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    content_object_id: Mapped[str] = mapped_column(
        ForeignKey("content_objects.id", ondelete="CASCADE"), index=True
    )
    source_asset_id: Mapped[str] = mapped_column(
        ForeignKey("content_assets.id", ondelete="CASCADE")
    )
    artifact_type: Mapped[str] = mapped_column(String(32))
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer())
    storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(80), nullable=True)
    text_content: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
