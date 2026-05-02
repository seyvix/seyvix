from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class SnapshotUserSettings(Base):
    __tablename__ = "snapshot_user_settings"

    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    archive_as_screenshot: Mapped[bool | None] = mapped_column(nullable=True)
    archive_as_webpage_html: Mapped[bool | None] = mapped_column(nullable=True)
    archive_as_pdf: Mapped[bool | None] = mapped_column(nullable=True)
    archive_as_markdown: Mapped[bool | None] = mapped_column(nullable=True)
    archive_as_archive_org: Mapped[bool | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class SnapshotJob(Base):
    __tablename__ = "snapshot_jobs"
    __table_args__ = (
        UniqueConstraint(
            "content_object_id",
            "source_asset_id",
            "job_type",
            name="uq_snapshot_jobs_object_asset_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    content_object_id: Mapped[str] = mapped_column(
        ForeignKey("content_objects.id", ondelete="CASCADE"),
        index=True,
    )
    source_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_assets.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    job_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer(), default=0)
    max_attempts: Mapped[int] = mapped_column(Integer(), default=3)
    correlation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    source_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    metadata_: Mapped[dict[str, object]] = mapped_column("metadata", JSON(), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SnapshotArtifact(Base):
    __tablename__ = "snapshot_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "content_object_id",
            "source_asset_id",
            "artifact_type",
            name="uq_snapshot_artifacts_object_asset_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    content_object_id: Mapped[str] = mapped_column(
        ForeignKey("content_objects.id", ondelete="CASCADE"),
        index=True,
    )
    source_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_assets.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    artifact_type: Mapped[str] = mapped_column(String(32), index=True)
    filename: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer())
    storage_path: Mapped[str] = mapped_column(String(2048))
    storage_backend: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bucket: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    storage_ref: Mapped[str | None] = mapped_column(String(2300), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ready", index=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
