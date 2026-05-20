from __future__ import annotations

import copy
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from app.contracts.events import EventEnvelope, SnapshotTextRepresentationCompletedPayload
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
from app.platform.events.outbox import EventOutboxRepository
from app.platform.storage.repositories import StorageObjectRepository
from app.platform.storage.service import LocalVolumeStorage, StorageBackend, StorageKeyBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


def extraction_metadata_from_generated_artifact(
    generated: GeneratedArtifact,
) -> dict[str, object] | None:
    if generated.metadata_path is None or not generated.metadata_path.exists():
        return None
    try:
        value = json.loads(generated.metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


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
        self.outbox = EventOutboxRepository(session)

    async def run_once(self, limit: int | None = None) -> int:
        jobs = await self.jobs.list_pending(limit or get_settings().snapshot_worker_batch_size)
        processed = 0
        for job in jobs:
            await self._process_job(job)
            processed += 1
            await self.session.commit()
        if processed == 0:
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
        if processed == 0:
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
        logger.info(
            "snapshot.job.loaded",
            job_id=job.id,
            job_type=job.job_type,
            content_object_id=job.content_object_id,
            source_asset_id=job.source_asset_id,
            asset_found=asset is not None,
            asset_media_type=asset.media_type if asset is not None else None,
            asset_mime_type=asset.mime_type if asset is not None else None,
        )

        pregenerated_artifact_id: str | None = None
        if job.job_type == "webpage_html" and asset is not None and asset.media_type == "link":
            pregenerated_artifact_id = str(uuid4())
            logger.info(
                "snapshot.job.webpage_html_artifact_id_pregenerated",
                job_id=job.id,
                source_asset_id=asset.id,
                artifact_id=pregenerated_artifact_id,
            )

        try:
            generated = self._generate_with_storage(
                content_object=content_object,
                asset=asset,
                job=job,
                artifact_id=pregenerated_artifact_id,
            )
            logger.info(
                "snapshot.job.generated",
                job_id=job.id,
                job_type=job.job_type,
                filename=generated.filename,
                mime_type=generated.mime_type,
                size_bytes=generated.path.stat().st_size if generated.path.exists() else None,
                has_resources=generated.resources_dir is not None,
                resources_dir=(
                    str(generated.resources_dir) if generated.resources_dir is not None else None
                ),
            )
        except UnsupportedSnapshotError as exc:
            logger.warning(
                "snapshot.job.unsupported",
                job_id=job.id,
                job_type=job.job_type,
                error=str(exc),
            )
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

        artifact_id = pregenerated_artifact_id or str(uuid4())
        stored = self.storage_backend.put_bytes(
            storage_key=StorageKeyBuilder.snapshot_artifact(
                content_object_id=job.content_object_id,
                snapshot_id=job.id,
                filename=generated.filename,
            ),
            data=generated.path.read_bytes(),
            content_type=generated.mime_type,
        )
        extraction_metadata = extraction_metadata_from_generated_artifact(generated)
        storage_metadata: dict[str, object] = {
            "job_type": job.job_type,
            "source_asset_id": job.source_asset_id,
        }
        if extraction_metadata is not None:
            storage_metadata["extraction"] = extraction_metadata
            job.metadata_ = {**(job.metadata_ or {}), "extraction": extraction_metadata}

        await self.storage_objects.upsert(
            stored,
            owner_entity_type="snapshot_artifact",
            owner_entity_id=artifact_id,
            metadata=storage_metadata,
        )
        if generated.metadata_path is not None and generated.metadata_path.exists():
            self.storage_backend.put_bytes(
                storage_key=StorageKeyBuilder.snapshot_artifact(
                    content_object_id=job.content_object_id,
                    snapshot_id=job.id,
                    filename=generated.metadata_path.name,
                ),
                data=generated.metadata_path.read_bytes(),
                content_type="application/json",
            )
        if generated.resources_dir is not None and generated.resources_dir.exists():
            manifest_file = generated.resources_dir.parent / "manifest.json"
            if manifest_file.exists():
                self.storage_backend.put_bytes(
                    storage_key=StorageKeyBuilder.snapshot_artifact_manifest(
                        content_object_id=job.content_object_id,
                        snapshot_id=job.id,
                    ),
                    data=manifest_file.read_bytes(),
                    content_type="application/json",
                )
            for resource_file in sorted(generated.resources_dir.iterdir()):
                if not resource_file.is_file():
                    continue
                self.storage_backend.put_bytes(
                    storage_key=StorageKeyBuilder.snapshot_artifact_resource(
                        content_object_id=job.content_object_id,
                        snapshot_id=job.id,
                        filename=resource_file.name,
                    ),
                    data=resource_file.read_bytes(),
                    content_type=None,
                )
            logger.info(
                "snapshot.job.resources_stored",
                job_id=job.id,
                artifact_id=artifact_id,
                resource_count=len([p for p in generated.resources_dir.iterdir() if p.is_file()]),
                manifest_exists=manifest_file.exists(),
            )
        artifact = SnapshotArtifact(
            id=artifact_id,
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
        await self.artifacts.upsert_ready(artifact)
        logger.info(
            "snapshot.job.artifact_record_created",
            job_id=job.id,
            artifact_id=artifact.id,
            artifact_type=artifact.artifact_type,
            source_asset_id=artifact.source_asset_id,
            storage_key=artifact.storage_key,
            status=artifact.status,
        )

        if (
            job.job_type == "thumbnail"
            and asset is not None
            and generated.width
            and generated.height
        ):
            asset.image_width = generated.width
            asset.image_height = generated.height

        job.status = "done"
        job.error_message = None
        job.last_error = None
        job.finished_at = datetime.now(UTC)
        if (
            job.job_type == "markdown"
            and asset is not None
            and await self._all_text_representation_jobs_finished(
                content_object_id=job.content_object_id
            )
        ):
            self._enqueue_text_representation_completed_event(
                job=job,
                asset=asset,
                artifact=artifact,
                extraction_metadata=extraction_metadata,
            )

    def _generate_with_storage(
        self,
        *,
        content_object: ContentObject,
        asset: ContentAsset | None,
        job: SnapshotJob,
        artifact_id: str | None = None,
    ) -> GeneratedArtifact:
        if asset is None:
            generator = SnapshotArtifactGenerator(self.storage_root)
            return generator.generate(
                content_object=content_object,
                asset=asset,
                job_type=job.job_type,
                artifact_id=artifact_id,
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
                artifact_id=artifact_id,
            )
            stable_path = self.storage_root / ".snapshot-worker" / job.id / generated.filename
            stable_path.parent.mkdir(parents=True, exist_ok=True)
            stable_path.write_bytes(generated.path.read_bytes())
            stable_resources_dir: Path | None = None
            if generated.resources_dir is not None and generated.resources_dir.exists():
                stable_resources_dir = stable_path.parent / "resources"
                shutil.copytree(generated.resources_dir, stable_resources_dir)
                manifest_src = generated.resources_dir.parent / "manifest.json"
                if manifest_src.exists():
                    shutil.copy2(manifest_src, stable_path.parent / "manifest.json")
            stable_metadata_path: Path | None = None
            if generated.metadata_path is not None and generated.metadata_path.exists():
                stable_metadata_path = stable_path.with_suffix(".extraction.json")
                shutil.copy2(generated.metadata_path, stable_metadata_path)
            return type(generated)(
                filename=generated.filename,
                mime_type=generated.mime_type,
                path=stable_path,
                width=generated.width,
                height=generated.height,
                resources_dir=stable_resources_dir,
                metadata_path=stable_metadata_path,
            )

    @staticmethod
    def _fail_job(job: SnapshotJob, message: str) -> None:
        job.status = "failed"
        job.error_message = message[:4000]
        job.last_error = message[:4000]
        job.finished_at = datetime.now(UTC)

    def _enqueue_text_representation_completed_event(
        self,
        *,
        job: SnapshotJob,
        asset: ContentAsset,
        artifact: SnapshotArtifact,
        extraction_metadata: dict[str, object] | None,
    ) -> None:
        envelope = EventEnvelope.new(
            event_name="snapshot.text_representation.completed",
            entity_id=job.content_object_id,
            correlation_id=job.correlation_id or str(uuid4()),
            user_id=job.owner_user_id,
            payload=SnapshotTextRepresentationCompletedPayload(
                content_object_id=job.content_object_id,
                source_asset_id=asset.id,
                artifact_id=artifact.id,
                representation_type="markdown",
                source_media_type=asset.media_type,
                source_mime_type=asset.mime_type,
                source_filename=asset.filename,
                metadata={
                    "job_id": job.id,
                    "job_type": job.job_type,
                    "source_event_id": job.source_event_id,
                    "extraction": extraction_metadata,
                },
            ),
        )
        self.outbox.add(envelope, routing_key="snapshot.text_representation.completed")

    async def _all_text_representation_jobs_finished(self, *, content_object_id: str) -> bool:
        unfinished_count = await self.session.scalar(
            select(func.count())
            .select_from(SnapshotJob)
            .where(
                SnapshotJob.content_object_id == content_object_id,
                SnapshotJob.job_type == "markdown",
                SnapshotJob.status.in_(("pending", "processing", "retrying")),
            )
        )
        return int(unfinished_count or 0) == 0
