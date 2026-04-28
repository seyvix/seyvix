from __future__ import annotations

import asyncio

from faststream.rabbit import RabbitBroker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts.events import EventEnvelope
from app.core.config import Settings
from app.core.logging import get_logger
from app.platform.events.models import EventOutbox
from app.platform.events.outbox import EventOutboxRepository

logger = get_logger(__name__)


class RabbitEventPublisher:
    def __init__(self, broker: RabbitBroker) -> None:
        self.broker = broker

    async def publish_outbox_event(self, event: EventOutbox) -> None:
        envelope = EventEnvelope(
            event_id=event.event_id,
            event_name=event.event_name,  # type: ignore[arg-type]
            event_version=event.event_version,
            occurred_at=event.occurred_at,
            correlation_id=event.correlation_id,
            user_id=event.user_id,
            entity_id=event.entity_id,
            payload=event.payload,
        )
        await self.broker.publish(
            envelope.model_dump(mode="json"),
            exchange=event.exchange_name,
            routing_key=event.routing_key,
            persist=True,
            correlation_id=event.correlation_id,
            message_id=event.event_id,
            message_type=event.event_name,
        )


class OutboxPublisher:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        publisher: RabbitEventPublisher,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.publisher = publisher

    async def publish_once(self) -> int:
        async with self.session_factory() as session:
            outbox = EventOutboxRepository(session)
            events = await outbox.list_pending(limit=self.settings.outbox_publisher_batch_size)
            for event in events:
                try:
                    await self.publisher.publish_outbox_event(event)
                    outbox.mark_published(event)
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "outbox.publish.failed",
                        event_id=event.event_id,
                        routing_key=event.routing_key,
                        error=str(exc),
                        exc_info=True,
                    )
                    outbox.mark_failed(event, str(exc))
            await session.commit()
            return len(events)

    async def run_forever(self) -> None:
        while True:
            processed = await self.publish_once()
            if processed:
                logger.info("outbox.publish.batch.done", processed=processed)
            await asyncio.sleep(self.settings.outbox_publisher_poll_interval_seconds)
