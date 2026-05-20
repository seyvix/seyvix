from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.core.database import Base
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        Index("uq_tags_owner_user_id_slug", "owner_user_id", "slug", unique=True),
        Index("ix_tags_owner_user_id_is_archived", "owner_user_id", "is_archived"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    tag_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    aliases: Mapped[list[str]] = mapped_column(JSON(), default=list)
    created_by_type: Mapped[str] = mapped_column(String(32))
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(64))
    source_detail: Mapped[dict[str, object]] = mapped_column(JSON(), default=dict)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean(), default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    assignments: Mapped[list[ContentTagAssignment]] = relationship(back_populates="tag")


class ContentTagAssignment(Base):
    __tablename__ = "content_tag_assignments"
    __table_args__ = (
        Index("ix_content_tag_assignments_owner_content", "owner_user_id", "content_object_id"),
        Index("ix_content_tag_assignments_owner_tag", "owner_user_id", "tag_id"),
        Index("ix_content_tag_assignments_owner_status", "owner_user_id", "status"),
        CheckConstraint(
            "status in ('suggested', 'accepted', 'rejected', 'removed')",
            name="ck_content_tag_assignments_status",
        ),
        Index(
            "uq_content_tag_assignments_active",
            "owner_user_id",
            "content_object_id",
            "tag_id",
            unique=True,
            postgresql_where=text("status in ('suggested', 'accepted')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    content_object_id: Mapped[str] = mapped_column(
        ForeignKey("content_objects.id", ondelete="CASCADE"), index=True
    )
    tag_id: Mapped[str] = mapped_column(ForeignKey("tags.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(32))
    assigned_by_type: Mapped[str] = mapped_column(String(32))
    assigned_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(64))
    source_detail: Mapped[dict[str, object]] = mapped_column(JSON(), default=dict)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    tag: Mapped[Tag] = relationship(back_populates="assignments")


class TaggingJob(Base):
    __tablename__ = "tagging_jobs"
    __table_args__ = (
        Index("ix_tagging_jobs_status_run_after_priority", "status", "run_after", "priority"),
        Index("ix_tagging_jobs_owner_content", "owner_user_id", "content_object_id"),
        UniqueConstraint("source_event_id", name="uq_tagging_jobs_source_event_id"),
        CheckConstraint(
            "status in ('pending', 'processing', 'succeeded', 'failed', 'cancelled', 'stale')",
            name="ck_tagging_jobs_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    job_type: Mapped[str] = mapped_column(String(64))
    content_object_id: Mapped[str] = mapped_column(
        ForeignKey("content_objects.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    priority: Mapped[int] = mapped_column(Integer(), default=100)
    attempts: Mapped[int] = mapped_column(Integer(), default=0)
    max_attempts: Mapped[int] = mapped_column(Integer(), default=3)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    content_updated_at_snapshot: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
