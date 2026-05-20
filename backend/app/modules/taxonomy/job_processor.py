from __future__ import annotations

from uuid import uuid4

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.modules.taxonomy.service import TaxonomyService
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


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
