from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.platform.jobs import JobColumnsMixin, job_queue_indexes

ACTIVE_ASSIGNMENT_STATUSES = ("suggested", "accepted")
TAGGING_JOB_SUGGEST = "suggest_content_tags"


def utcnow() -> datetime:
    return datetime.now(UTC)


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        Index("uq_tags_owner_user_id_slug", "owner_user_id", "slug", unique=True),
        Index("ix_tags_owner_user_id_is_archived", "owner_user_id", "is_archived"),
        # Alias lookups (`aliases ?| array[...]`) when resolving suggested/typed names.
        Index("ix_tags_aliases", "aliases", postgresql_using="gin"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    tag_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Alias slugs (see `app.modules.tags.text.slugify_label`).
    aliases: Mapped[list[str]] = mapped_column(JSONB(), default=list)
    created_by_type: Mapped[str] = mapped_column(String(32))
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(64))
    source_detail: Mapped[dict[str, object]] = mapped_column(JSONB(), default=dict)
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
            name="status",
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
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
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
    source_detail: Mapped[dict[str, object]] = mapped_column(JSONB(), default=dict)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    tag: Mapped[Tag] = relationship(back_populates="assignments")


class TaggingJob(JobColumnsMixin, Base):
    """At most one row per (content object, job type); re-runs reset the row.

    `rerun_requested` is set when new input arrives while the job is processing: the
    running attempt finishes, then the row goes back to pending instead of succeeded.
    """

    __tablename__ = "tagging_jobs"
    __table_args__ = (
        *job_queue_indexes("tagging_jobs"),
        UniqueConstraint(
            "content_object_id", "job_type", name="uq_tagging_jobs_content_object_id_job_type"
        ),
        Index("ix_tagging_jobs_owner_status", "owner_user_id", "status"),
        CheckConstraint(
            "status in ('pending', 'processing', 'succeeded', 'failed', 'cancelled')",
            name="status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    content_object_id: Mapped[str] = mapped_column(
        ForeignKey("content_objects.id", ondelete="CASCADE")
    )
    job_type: Mapped[str] = mapped_column(String(64), default=TAGGING_JOB_SUGGEST)
    rerun_requested: Mapped[bool] = mapped_column(Boolean(), default=False)
    source_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
