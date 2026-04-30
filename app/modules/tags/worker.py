from __future__ import annotations

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.modules.llm.contracts import StructuredLLMGenerator
from app.modules.tags.service import TagsService

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
            processed += 1
        await self.session.commit()
        return processed
