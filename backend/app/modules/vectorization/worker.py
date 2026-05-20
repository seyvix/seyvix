from __future__ import annotations

from uuid import uuid4

from app.contracts.events import EventEnvelope
from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.vectorization.service import VectorizationService
from app.platform.events.idempotency import EventAlreadyProcessedError, ProcessedEventStore
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class VectorizationEventConsumer:
    consumer_name = "vectorization-event-consumer"

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.idempotency = ProcessedEventStore(session)

    async def handle_event(self, envelope: EventEnvelope) -> int:
        try:
            await self.idempotency.mark_processing(
                event_id=envelope.event_id,
                consumer_name=self.consumer_name,
            )
        except EventAlreadyProcessedError:
            logger.info(
                "vectorization.event.duplicate",
                event_id=envelope.event_id,
                correlation_id=envelope.correlation_id,
            )
            return 0

        owner_user_id = envelope.user_id
        content_object_id = str(envelope.payload.get("content_object_id") or envelope.entity_id)
        if owner_user_id is None:
            logger.warning(
                "vectorization.event.missing_user",
                event_id=envelope.event_id,
                correlation_id=envelope.correlation_id,
            )
            await self.session.commit()
            return 0

        service = VectorizationService(self.session)
        if envelope.event_name == "content.object.deleted":
            await service.delete_source_vectors(
                owner_user_id=owner_user_id,
                source="content",
                source_type="content_object",
                source_id=content_object_id,
            )
            return 1

        if envelope.event_name != "snapshot.text_representation.completed":
            await self.session.commit()
            return 0

        await service.enqueue_index_request(
            owner_user_id=owner_user_id,
            source="content",
            source_type="content_object",
            source_id=content_object_id,
            priority=100,
            reason="Triggered by completed snapshot text representation.",
        )
        return 1


class VectorizationWorker:
    def __init__(self, session: AsyncSession, *, worker_id: str | None = None) -> None:
        self.session = session
        self.worker_id = worker_id or f"vectorization-worker-{uuid4()}"

    async def run_once(self, limit: int | None = None) -> int:
        settings = get_settings()
        service = VectorizationService(self.session, settings=settings)
        jobs = await service.repository.claim_pending_jobs(
            limit=limit or settings.vector_worker_batch_size,
            worker_id=self.worker_id,
            lock_timeout_seconds=settings.vector_worker_lock_timeout_seconds,
        )
        processed = 0
        for job in jobs:
            try:
                await service.process_job(job)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "vectorization.job.error",
                    job_id=job.id,
                    source=job.source,
                    source_type=job.source_type,
                    source_id=job.source_id,
                    error=str(exc),
                    exc_info=True,
                )
                await service.mark_failed(job, str(exc) or exc.__class__.__name__)
            processed += 1
        await self.session.commit()
        return processed
