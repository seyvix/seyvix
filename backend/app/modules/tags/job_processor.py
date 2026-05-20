from __future__ import annotations

from uuid import uuid4

from app.contracts.events import ContentTagsCompletedPayload, EventEnvelope
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.modules.llm.contracts import StructuredLLMGenerator
from app.modules.tags.models import TaggingJob
from app.modules.tags.service import TagsService
from app.platform.events.outbox import EventOutboxRepository
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class TagsWorker:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings | None = None,
        llm_generator: StructuredLLMGenerator | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.llm_generator = llm_generator
        self.worker_id = worker_id or f"tags-worker-{uuid4()}"
        self.outbox = EventOutboxRepository(session)

    async def run_once(self, limit: int | None = None) -> int:
        service = TagsService(
            self.session,
            settings=self.settings,
            llm_generator=self.llm_generator,
        )
        jobs = await service.repository.claim_pending_jobs(
            limit=limit or self.settings.tags_worker_batch_size,
            worker_id=self.worker_id,
            lock_timeout_seconds=self.settings.tags_worker_lock_timeout_seconds,
        )
        processed = 0
        for job in jobs:
            try:
                await service.process_job(job)
            except Exception as exc:  # noqa: BLE001
                error = str(exc) or exc.__class__.__name__
                logger.error(
                    "tags.job.error",
                    job_id=job.id,
                    content_object_id=job.content_object_id,
                    error=error,
                    exc_info=True,
                )
                await service.mark_failed(job, error)
            if job.status in {"succeeded", "failed", "stale"}:
                self._enqueue_tags_completed_event(job)
            processed += 1
        await self.session.commit()
        return processed

    def _enqueue_tags_completed_event(self, job: TaggingJob) -> None:
        envelope = EventEnvelope.new(
            event_name="content.tags.completed",
            entity_id=job.content_object_id,
            correlation_id=job.correlation_id or str(uuid4()),
            user_id=job.owner_user_id,
            payload=ContentTagsCompletedPayload(
                content_object_id=job.content_object_id,
                tagging_job_id=job.id,
                job_type=job.job_type,
                status=job.status,
                metadata={
                    "source_event_id": job.source_event_id,
                    "attempts": job.attempts,
                },
            ),
        )
        self.outbox.add(envelope, routing_key="content.tags.completed")
