from __future__ import annotations

from uuid import uuid4

from app.contracts.events import EventEnvelope
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.modules.taxonomy.service import TaxonomyNotFoundError, TaxonomyService
from app.platform.events.idempotency import EventAlreadyProcessedError, ProcessedEventStore
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class TaxonomyEventConsumer:
    consumer_name = "taxonomy-event-consumer"

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
                "taxonomy.event.duplicate",
                event_id=envelope.event_id,
                correlation_id=envelope.correlation_id,
            )
            return 0

        if envelope.event_name == "content.object.deleted":
            await self.session.commit()
            return 0
        if envelope.event_name not in {"content.object.created", "content.object.updated"}:
            await self.session.commit()
            return 0

        owner_user_id = envelope.user_id
        content_object_id = str(envelope.payload.get("content_object_id") or envelope.entity_id)
        if owner_user_id is None:
            logger.warning(
                "taxonomy.event.missing_user",
                event_id=envelope.event_id,
                correlation_id=envelope.correlation_id,
            )
            await self.session.commit()
            return 0

        try:
            await TaxonomyService(self.session).enqueue_classification_job(
                owner_user_id=owner_user_id,
                content_object_id=content_object_id,
                priority=100,
                source_event_id=envelope.event_id,
                correlation_id=envelope.correlation_id,
            )
        except TaxonomyNotFoundError:
            logger.warning(
                "taxonomy.event.content_object_missing",
                event_id=envelope.event_id,
                correlation_id=envelope.correlation_id,
                content_object_id=content_object_id,
            )
            await self.session.commit()
            return 0

        await self.session.commit()
        return 1


class TaxonomyWorker:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.worker_id = worker_id or f"taxonomy-worker-{uuid4()}"

    async def run_once(self, limit: int | None = None) -> int:
        service = TaxonomyService(self.session, settings=self.settings)
        jobs = await service.repository.claim_pending_classification_jobs(
            limit=limit or self.settings.taxonomy_worker_batch_size,
            worker_id=self.worker_id,
            lock_timeout_seconds=self.settings.taxonomy_worker_lock_timeout_seconds,
        )
        processed = 0
        for job in jobs:
            try:
                await service.process_classification_job(job)
            except Exception as exc:  # noqa: BLE001
                error = str(exc) or exc.__class__.__name__
                logger.error(
                    "taxonomy.job.error",
                    job_id=job.id,
                    content_object_id=job.content_object_id,
                    error=error,
                    exc_info=True,
                )
                await service.mark_classification_failed(job, error)
            processed += 1
        await self.session.commit()
        return processed
