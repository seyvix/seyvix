from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.platform.jobs import JobColumnsMixin, job_queue_indexes, utcnow


class Event(Base):
    """Immutable domain event log, written in the producer's transaction."""

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer(), default=1)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    correlation_id: Mapped[str] = mapped_column(String(36))
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    entity_id: Mapped[str] = mapped_column(String(36))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB(), default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class EventDelivery(JobColumnsMixin, Base):
    """One row per (event, consumer): an independent per-consumer queue.

    Status lifecycle follows `app.platform.jobs` (pending -> processing -> succeeded|failed).
    A `failed` row is the dead-letter entry for that consumer.
    """

    __tablename__ = "event_deliveries"
    __table_args__ = (
        UniqueConstraint("event_id", "consumer"),
        *job_queue_indexes("event_deliveries"),
        Index("ix_event_deliveries_consumer_status", "consumer", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    consumer: Mapped[str] = mapped_column(String(64))
    event: Mapped[Event] = relationship(lazy="raise")
