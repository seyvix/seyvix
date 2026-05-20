from __future__ import annotations

from app.contracts.events import EventEnvelope
from app.core.logging import get_logger
from app.modules.tags.infrastructure.repositories import TagsRepository
from app.platform.events.idempotency import EventAlreadyProcessedError, ProcessedEventStore
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class TagsEventConsumer:
    consumer_name = "tags-event-consumer"

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = TagsRepository(session)
        self.idempotency = ProcessedEventStore(session)

    async def handle_event(self, envelope: EventEnvelope) -> int:
        try:
            await self.idempotency.mark_processing(
                event_id=envelope.event_id,
                consumer_name=self.consumer_name,
            )
        except EventAlreadyProcessedError:
            logger.info(
                "tags.event.duplicate",
                event_id=envelope.event_id,
                correlation_id=envelope.correlation_id,
            )
            return 0

        if envelope.event_name != "snapshot.text_representation.completed":
            await self.session.commit()
            return 0

        owner_user_id = envelope.user_id
        content_object_id = str(envelope.payload.get("content_object_id") or envelope.entity_id)
        if owner_user_id is None:
            logger.warning(
                "tags.event.missing_user",
                event_id=envelope.event_id,
                correlation_id=envelope.correlation_id,
            )
            await self.session.commit()
            return 0

        await self.repository.enqueue_job(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            job_type="suggest_content_tags",
            priority=100,
            source_event_id=envelope.event_id,
            correlation_id=envelope.correlation_id,
        )
        await self.session.commit()
        return 1
