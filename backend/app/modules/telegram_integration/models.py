from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

BOT_MODE_AUTO = "auto"
BOT_MODE_SEPARATE = "separate"
BOT_MODE_MANUAL_COLLECTION = "manual_collection"
BOT_MODES = (BOT_MODE_AUTO, BOT_MODE_SEPARATE, BOT_MODE_MANUAL_COLLECTION)


def utcnow() -> datetime:
    return datetime.now(UTC)


class TelegramBotState(Base):
    """Per-Telegram-user bot preferences; the bot reads/writes it via the internal API."""

    __tablename__ = "telegram_bot_states"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('auto', 'separate', 'manual_collection')",
            name="ck_telegram_bot_states_mode",
        ),
        Index(
            "ix_telegram_bot_states_reminder_due",
            "manual_collection_last_item_at",
            postgresql_where=text(
                "mode = 'manual_collection' AND active_collection_id IS NOT NULL "
                "AND manual_collection_reminder_sent_at IS NULL"
            ),
        ),
    )

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    mode: Mapped[str] = mapped_column(String(32), default=BOT_MODE_AUTO)
    active_collection_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_objects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    manual_collection_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    manual_collection_last_item_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    manual_collection_reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
