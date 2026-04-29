from __future__ import annotations

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.vectorization.service import VectorizationService

logger = get_logger(__name__)


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
