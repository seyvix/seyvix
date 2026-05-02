from __future__ import annotations

import copy
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.events import EventEnvelope
from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.content.models import ContentAsset, ContentObject
from app.modules.snapshots.artifacts import (
    GeneratedArtifact,
    SnapshotArtifactGenerator,
    UnsupportedSnapshotError,
)
from app.modules.snapshots.infrastructure.repositories import (
    SnapshotArtifactRepository,
    SnapshotContentRepository,
    SnapshotJobRepository,
)
from app.modules.snapshots.models import SnapshotArtifact, SnapshotJob
from app.modules.snapshots.service import SnapshotService
from app.platform.events.idempotency import EventAlreadyProcessedError, ProcessedEventStore
from app.platform.storage.repositories import StorageObjectRepository
from app.platform.storage.service import LocalVolumeStorage, StorageBackend, StorageKeyBuilder

logger = get_logger(__name__)


class SnapshotWorker:
    consumer_name = "snapshot-worker"

    def __init__(
        self,
        session: AsyncSession,
        storage_root: Path | None = None,
        storage_backend: StorageBackend | None = None,
    ) -> None:
        self.session = session
        self.storage_root = storage_root or Path("data/content")
        self.storage_backend = storage_backend or LocalVolumeStorage(
            root=self.storage_root,
            bucket=get_settings().s3_bucket,
        )
        self.jobs = SnapshotJobRepository(session)
        self.artifacts = SnapshotArtifactRepository(session)
        self.content = SnapshotContentRepository(session)
        self.storage_objects = StorageObjectRepository(session)
        self.idempotency = ProcessedEventStore(session)

    async def run_once(self, limit: int | None = None) -> int:
        jobs = await self.jobs.list_pending(limit or get_settings().snapshot_worker_batch_size)
        processed = 0
        for job in jobs:
            await self._process_job(job)
            processed += 1
        await self.session.commit()
        return processed

    async def handle_event(self, envelope: EventEnvelope) -> int:
        try:
            await self.idempotency.mark_processing(
                event_id=envelope.event_id,
                consumer_name=self.consumer_name,
            )
        except EventAlreadyProcessedError:
            logger.info(
                "snapshot.event.duplicate",
                event_id=envelope.event_id,
                correlation_id=envelope.correlation_id,
            )
            return 0

        content_object = await self.content.get_object(envelope.entity_id)
        if content_object is None:
            logger.warning(
                "snapshot.event.content_object_missing",
                event_id=envelope.event_id,
                correlation_id=envelope.correlation_id,
                content_object_id=envelope.entity_id,
            )
            await self.session.commit()
            return 0

        await SnapshotService(
            self.session,
            self.storage_root,
            self.storage_backend,
        ).enqueue_for_content_object(
            content_object,
            correlation_id=envelope.correlation_id,
            source_event_id=envelope.event_id,
        )
        jobs = await self.jobs.list_pending_for_object(
            content_object_id=content_object.id,
            limit=get_settings().snapshot_worker_batch_size,
        )
        processed = 0
        for job in jobs:
            await self._process_job(job)
            processed += 1
        await self.session.commit()
        return processed

    async def _process_job(self, job: SnapshotJob) -> None:
        job.status = "processing"
        job.attempts += 1
        job.started_at = datetime.now(UTC)
        await self.session.flush()

        content_object = await self.content.get_object(job.content_object_id)
        asset = await self.content.get_asset(job.source_asset_id) if job.source_asset_id else None
        if content_object is None:
            self._fail_job(job, "Content object not found.")
            return

        try:
            generated = self._generate_with_storage(
                content_object=content_object,
                asset=asset,
                job=job,
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

        stored = self.storage_backend.put_bytes(
            storage_key=StorageKeyBuilder.snapshot_artifact(
                content_object_id=job.content_object_id,
                snapshot_id=job.id,
                filename=generated.filename,
            ),
            data=generated.path.read_bytes(),
            content_type=generated.mime_type,
        )
        self.storage_objects.add(
            stored,
            owner_entity_type="snapshot_artifact",
            owner_entity_id=job.id,
            metadata={"job_type": job.job_type, "source_asset_id": job.source_asset_id},
        )
        artifact = SnapshotArtifact(
            owner_user_id=job.owner_user_id,
            content_object_id=job.content_object_id,
            source_asset_id=job.source_asset_id,
            artifact_type=job.job_type,
            filename=generated.filename,
            mime_type=generated.mime_type,
            size_bytes=stored.size_bytes,
            storage_path=stored.storage_key,
            storage_backend=stored.storage_backend,
            bucket=stored.bucket,
            storage_key=stored.storage_key,
            storage_ref=stored.storage_ref,
            checksum=stored.checksum,
            status="ready",
        )
        self.artifacts.add(artifact)

        if job.job_type == "thumbnail" and asset is not None and generated.width and generated.height:
            asset.image_width = generated.width
            asset.image_height = generated.height

        job.status = "done"
        job.error_message = None
        job.last_error = None
        job.finished_at = datetime.now(UTC)

    def _generate_with_storage(
        self,
        *,
        content_object: ContentObject,
        asset: ContentAsset | None,
        job: SnapshotJob,
    ) -> GeneratedArtifact:
        if asset is None:
            generator = SnapshotArtifactGenerator(self.storage_root)
            return generator.generate(
                content_object=content_object, asset=asset, job_type=job.job_type
            )

        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_key = asset.storage_key or asset.storage_path
            source_path = temp_root / source_key
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_bytes(self.storage_backend.get_bytes(source_key))

            local_content_object = copy.copy(content_object)
            local_content_object.storage_path = f"content-assets/{content_object.id}"
            local_asset = copy.copy(asset)
            local_asset.storage_path = source_key

            generator = SnapshotArtifactGenerator(temp_root)
            generated = generator.generate(
                content_object=local_content_object,
                asset=local_asset,
                job_type=job.job_type,
            )
            stable_path = self.storage_root / ".snapshot-worker" / job.id / generated.filename
            stable_path.parent.mkdir(parents=True, exist_ok=True)
            stable_path.write_bytes(generated.path.read_bytes())
            return type(generated)(
                filename=generated.filename,
                mime_type=generated.mime_type,
                path=stable_path,
                width=generated.width,
                height=generated.height,
            )

    @staticmethod
    def _fail_job(job: SnapshotJob, message: str) -> None:
        job.status = "failed"
        job.error_message = message[:4000]
        job.last_error = message[:4000]
        job.finished_at = datetime.now(UTC)
