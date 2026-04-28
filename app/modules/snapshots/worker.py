from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.snapshots.artifacts import SnapshotArtifactGenerator, UnsupportedSnapshotError
from app.modules.snapshots.infrastructure.repositories import (
    SnapshotArtifactRepository,
    SnapshotContentRepository,
    SnapshotJobRepository,
)
from app.modules.snapshots.models import SnapshotArtifact, SnapshotJob

logger = get_logger(__name__)


class SnapshotWorker:
    def __init__(self, session: AsyncSession, storage_root: Path | None = None) -> None:
        self.session = session
        self.storage_root = storage_root or Path("data/content")
        self.jobs = SnapshotJobRepository(session)
        self.artifacts = SnapshotArtifactRepository(session)
        self.content = SnapshotContentRepository(session)
        self.generator = SnapshotArtifactGenerator(self.storage_root)

    async def run_once(self, limit: int | None = None) -> int:
        jobs = await self.jobs.list_pending(limit or get_settings().snapshot_worker_batch_size)
        processed = 0
        for job in jobs:
            await self._process_job(job)
            processed += 1
        await self.session.commit()
        return processed

    async def _process_job(self, job: SnapshotJob) -> None:
        job.status = "processing"
        job.attempts += 1
        await self.session.flush()

        content_object = await self.content.get_object(job.content_object_id)
        asset = await self.content.get_asset(job.source_asset_id) if job.source_asset_id else None
        if content_object is None:
            self._fail_job(job, "Content object not found.")
            return

        try:
            generated = self.generator.generate(
                content_object=content_object,
                asset=asset,
                job_type=job.job_type,
            )
        except UnsupportedSnapshotError as exc:
            self._fail_job(job, str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "snapshot.job.error",
                job_id=job.id,
                job_type=job.job_type,
                error=str(exc),
                exc_info=True,
            )
            self._fail_job(job, str(exc))
            return

        artifact = SnapshotArtifact(
            owner_user_id=job.owner_user_id,
            content_object_id=job.content_object_id,
            source_asset_id=job.source_asset_id,
            artifact_type=job.job_type,
            filename=generated.filename,
            mime_type=generated.mime_type,
            size_bytes=generated.size_bytes,
            storage_path=generated.path.relative_to(self.storage_root).as_posix(),
            status="ready",
        )
        self.artifacts.add(artifact)
        job.status = "done"
        job.error_message = None
        job.finished_at = datetime.now(UTC)

    @staticmethod
    def _fail_job(job: SnapshotJob, message: str) -> None:
        job.status = "failed"
        job.error_message = message[:4000]
        job.finished_at = datetime.now(UTC)
