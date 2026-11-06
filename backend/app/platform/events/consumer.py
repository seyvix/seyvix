from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import joinedload

from app.contracts.events import EventEnvelope
from app.core.logging import get_logger
from app.platform.events.models import EventDelivery
from app.platform.events.outbox import envelope_from_event
from app.platform.jobs import JOB_PENDING, JobQueue, utcnow

logger = get_logger(__name__)


class EventHandler(Protocol):
    """A module's reaction to a routed event.

    Contract: must be quick (enqueue module jobs / update rows), idempotent, and must NOT
    commit or roll back the session. The runner commits the handler's writes atomically
    with marking the delivery succeeded.
    """

    async def handle_event(self, envelope: EventEnvelope) -> None: ...


EventHandlerFactory = Callable[[AsyncSession], EventHandler]


class EventConsumerRunner:
    """Serves one consumer queue from `event_deliveries`."""

    def __init__(
        self,
        consumer: str,
        handler_factory: EventHandlerFactory,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        batch_size: int,
    ) -> None:
        self.consumer = consumer
        self.handler_factory = handler_factory
        self.session_factory = session_factory
        self.batch_size = batch_size

    async def run_once(self, limit: int | None = None) -> int:
        async with self.session_factory() as session:
            query = (
                select(EventDelivery)
                .options(joinedload(EventDelivery.event))
                .where(
                    EventDelivery.consumer == self.consumer,
                    EventDelivery.status == JOB_PENDING,
                    EventDelivery.run_after <= utcnow(),
                )
                .order_by(EventDelivery.priority.desc(), EventDelivery.run_after.asc())
                .limit(limit or self.batch_size)
                .with_for_update(skip_locked=True, of=EventDelivery)
            )
            deliveries = list((await session.scalars(query)).unique())
            for delivery in deliveries:
                delivery.attempts += 1
                envelope = envelope_from_event(delivery.event)
                try:
                    async with session.begin_nested():
                        await self.handler_factory(session).handle_event(envelope)
                except Exception as exc:  # noqa: BLE001 - isolate poison events
                    JobQueue.fail(delivery, f"{type(exc).__name__}: {exc}")
                    log = logger.error if delivery.status != JOB_PENDING else logger.warning
                    log(
                        "event.consume.failed",
                        consumer=self.consumer,
                        event_id=envelope.event_id,
                        event_name=envelope.event_name,
                        attempts=delivery.attempts,
                        status=delivery.status,
                        error=str(exc),
                        exc_info=True,
                    )
                    continue
                JobQueue.succeed(delivery)
            await session.commit()
            return len(deliveries)

    async def aclose(self) -> None:
        return None
