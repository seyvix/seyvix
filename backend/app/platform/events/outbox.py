from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.events import EventEnvelope
from app.contracts.events.routing import consumers_for
from app.platform.events.models import Event, EventDelivery
from app.platform.jobs import JOB_SUCCEEDED, utcnow


class EventPublisher:
    """Transactional outbox: stage an event plus one delivery per routed consumer in the
    caller's transaction. Nothing is visible to consumers until the caller commits; a
    database trigger then NOTIFYs listening workers."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def publish(self, envelope: EventEnvelope) -> Event:
        event = Event(
            id=envelope.event_id,
            name=envelope.event_name,
            version=envelope.event_version,
            occurred_at=envelope.occurred_at,
            correlation_id=envelope.correlation_id,
            user_id=envelope.user_id,
            entity_id=envelope.entity_id,
            payload=envelope.payload,
        )
        self.session.add(event)
        for consumer in consumers_for(envelope.event_name):
            self.session.add(EventDelivery(event_id=event.id, consumer=consumer))
        return event


def envelope_from_event(event: Event) -> EventEnvelope:
    return EventEnvelope(
        event_id=event.id,
        event_name=event.name,  # type: ignore[arg-type]
        event_version=event.version,
        occurred_at=event.occurred_at,
        correlation_id=event.correlation_id,
        user_id=event.user_id,
        entity_id=event.entity_id,
        payload=event.payload,
    )


async def prune_events(session: AsyncSession, *, older_than: timedelta) -> int:
    """Drop succeeded deliveries and fully-consumed events past retention.
    Failed deliveries (dead letters) are kept for inspection."""
    cutoff = utcnow() - older_than
    await session.execute(
        delete(EventDelivery).where(
            EventDelivery.status == JOB_SUCCEEDED, EventDelivery.updated_at < cutoff
        )
    )
    result = await session.execute(
        delete(Event).where(
            Event.created_at < cutoff,
            ~exists(select(EventDelivery.id).where(EventDelivery.event_id == Event.id)),
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)
