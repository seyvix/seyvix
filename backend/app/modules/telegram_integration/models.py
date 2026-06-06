from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class TelegramIngestState(Base):
    __tablename__ = "telegram_ingest_states"

    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    mode: Mapped[str] = mapped_column(String(32), default="default")
    active_collection_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_objects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    default_group_collection_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_objects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_group_collection_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_objects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_group_key: Mapped[str | None] = mapped_column(String(640), nullable=True, index=True)
    source_group_last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
