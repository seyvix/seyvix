from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.events import EventEnvelope
from app.platform.events.models import EventOutbox


class EventOutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(
        self,
        envelope: EventEnvelope,
        *,
        routing_key: str,
        exchange_name: str = "app.events",
    ) -> EventOutbox:
        event = EventOutbox(
            event_id=envelope.event_id,
            event_name=envelope.event_name,
            event_version=envelope.event_version,
            occurred_at=envelope.occurred_at,
            correlation_id=envelope.correlation_id,
            user_id=envelope.user_id,
            entity_id=envelope.entity_id,
            payload=envelope.payload,
            exchange_name=exchange_name,
            routing_key=routing_key,
            status="pending",
        )
        self.session.add(event)
        return event

    async def list_pending(self, *, limit: int) -> list[EventOutbox]:
        query = (
            select(EventOutbox)
            .where(EventOutbox.status == "pending")
            .order_by(EventOutbox.created_at.asc())
            .limit(limit)
        )
        return list(await self.session.scalars(query))

    def mark_published(self, event: EventOutbox) -> None:
        event.status = "published"
        event.last_error = None
        event.published_at = datetime.now(UTC)

    def mark_failed(self, event: EventOutbox, error: str) -> None:
        event.status = "failed"
        event.attempts += 1
        event.last_error = error[:4000]

    async def get_by_event_id(self, event_id: str) -> EventOutbox | None:
        return cast(
            EventOutbox | None,
            await self.session.scalar(select(EventOutbox).where(EventOutbox.event_id == event_id)),
        )
