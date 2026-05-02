from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.events.models import ProcessedEvent


class EventAlreadyProcessedError(Exception):
    pass


class ProcessedEventStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def mark_processing(self, *, event_id: str, consumer_name: str) -> None:
        self.session.add(ProcessedEvent(event_id=event_id, consumer_name=consumer_name))
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise EventAlreadyProcessedError(
                f"Event {event_id} was already processed by {consumer_name}."
            ) from exc
