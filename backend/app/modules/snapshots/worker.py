"""Snapshot worker: event handler (schedules jobs) and job runner (produces artifacts).

Runner protocol (see `app.platform.jobs`): claim every due job of one source asset in a short
transaction → generate all requested outputs with no DB connection held (one page render /
one office conversion / one extraction shared by all outputs) → upload files → finalize in
one short transaction (artifact rows replaced, job states, change-feed bump, text event) →
delete the replaced artifacts' files after commit.
"""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final
from uuid import uuid4

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.events import EventEnvelope, SnapshotTextRepresentationCompletedPayload
from app.core.logging import get_logger
from app.modules.content.models import ContentAsset
from app.modules.content.sync import touch_content_objects
from app.modules.snapshots.artifacts import (
    GeneratedArtifact,
    Outcome,
    SnapshotGenerator,
    SourceAsset,
)
from app.modules.snapshots.browser import BrowserManager
from app.modules.snapshots.egress import EgressProxy
from app.modules.snapshots.errors import SnapshotError
from app.modules.snapshots.extraction.ai import AIEnrichment
from app.modules.snapshots.models import SnapshotArtifact, SnapshotJob
from app.modules.snapshots.rewriter import mime_for_resource
from app.modules.snapshots.service import artifact_dir, schedule_content_object
from app.platform.events import EventPublisher
from app.platform.jobs import (
    JOB_ACTIVE_STATUSES,
    JOB_PENDING,
    JOB_PROCESSING,
    JobQueue,
)
from app.platform.storage.keys import asset_artifact_key
from app.platform.storage.service import StorageError
from app.worker.context import WorkerContext

logger = get_logger(__name__)

SCHEDULING_EVENTS: Final = frozenset({"content.object.created", "content.object.updated"})
BUSY_POLL_SECONDS: Final = 5.0
SHUTDOWN_GRACE_SECONDS: Final = 10.0
MAX_JOBS_PER_ASSET: Final = 16


# --- events ---------------------------------------------------------------------------------
class SnapshotEventHandler:
    """content.object.created/updated → queue snapshot jobs (idempotent, no commit)."""

    def __init__(self, session: AsyncSession, ctx: WorkerContext) -> None:
        self.session = session
        self.ctx = ctx

    async def handle_event(self, envelope: EventEnvelope) -> None:
        if envelope.event_name not in SCHEDULING_EVENTS:
            return
        queued = await schedule_content_object(
            self.session,
            envelope.entity_id,
            correlation_id=envelope.correlation_id,
            source_event_id=envelope.event_id,
        )
        if queued is None:
            return
        await self.session.flush()
        # Nothing (left) to extract: downstream consumers still get their trigger now.
        await publish_text_completed_if_settled(
            self.session,
            content_object_id=envelope.entity_id,
            owner_user_id=envelope.user_id,
            correlation_id=envelope.correlation_id,
        )


async def publish_text_completed_if_settled(
    session: AsyncSession,
    *,
    content_object_id: str,
    owner_user_id: str | None,
    correlation_id: str | None,
    asset: SourceAsset | None = None,
    artifact_id: str | None = None,
    metadata: dict[str, object] | None = None,
) -> bool:
    """Publish `snapshot.text_representation.completed` once no markdown job of the object
    is pending/processing. Serialized per object so concurrent finalizers cannot both miss
    the moment the last job settles. The caller must have flushed its own job update."""
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(content_object_id))))
    active = await session.scalar(
        select(
            exists().where(
                SnapshotJob.content_object_id == content_object_id,
                SnapshotJob.job_type == "markdown",
                SnapshotJob.status.in_(JOB_ACTIVE_STATUSES),
            )
        )
    )
    if active:
        return False
    EventPublisher(session).publish(
        EventEnvelope.new(
            event_name="snapshot.text_representation.completed",
            entity_id=content_object_id,
            correlation_id=correlation_id or str(uuid4()),
            user_id=owner_user_id,
            payload=SnapshotTextRepresentationCompletedPayload(
                content_object_id=content_object_id,
                source_asset_id=asset.id if asset is not None else None,
                artifact_id=artifact_id,
                source_media_type=asset.media_type if asset is not None else None,
                source_mime_type=asset.mime_type if asset is not None else None,
                source_filename=asset.filename if asset is not None else None,
                metadata=metadata or {},
            ),
        )
    )
    return True


# --- jobs -----------------------------------------------------------------------------------
@dataclass(slots=True)
class _Unit:
    """All claimed jobs of one source asset."""

    asset: SourceAsset
    owner_user_id: str
    correlation_id: str | None
    job_ids: dict[str, str]  # job_type -> job id
    artifact_ids: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _Stored:
    generated: GeneratedArtifact
    artifact_id: str
    key: str | None
    size_bytes: int
    checksum: str | None


class SnapshotJobRunner:
    def __init__(self, ctx: WorkerContext) -> None:
        settings = ctx.settings
        self.ctx = ctx
        self.queue = JobQueue(
            SnapshotJob, lease_seconds=settings.worker_job_lease_seconds, worker_id=ctx.worker_id
        )
        self.egress = EgressProxy()
        self.browser = BrowserManager(settings, self.egress)
        self.generator = SnapshotGenerator(
            settings, ctx.storage, self.browser, self.egress, AIEnrichment.from_settings(settings)
        )
        self.concurrency = settings.worker_snapshot_concurrency
        # Never outlive the lease: a job still running past it could be claimed twice.
        self.job_budget_seconds = max(settings.worker_job_lease_seconds - 60, 60)
        self._inflight: dict[asyncio.Task[None], _Unit] = {}

    async def run_once(self) -> int:
        claimed = 0
        while len(self._inflight) < self.concurrency:
            unit = await self._claim()
            if unit is None:
                break
            task = asyncio.create_task(self._process(unit), name=f"snapshot:{unit.asset.id}")
            self._inflight[task] = unit
            claimed += 1
        if not self._inflight:
            return 0
        done, _ = await asyncio.wait(
            self._inflight, timeout=BUSY_POLL_SECONDS, return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            self._inflight.pop(task, None)
            if not task.cancelled() and task.exception() is not None:
                logger.error(
                    "snapshot.unit.crashed", error=str(task.exception()), exc_info=task.exception()
                )
        # Busy (or just finished work): ask the supervisor to call again right away.
        return claimed + len(done) + len(self._inflight)

    async def aclose(self) -> None:
        if self._inflight:
            await asyncio.wait(self._inflight, timeout=SHUTDOWN_GRACE_SECONDS)
        for task in self._inflight:
            task.cancel()
        await asyncio.gather(*self._inflight, return_exceptions=True)
        self._inflight.clear()
        await self.browser.aclose()
        await self.egress.aclose()

    # --- claim ---------------------------------------------------------------------------
    async def _claim(self) -> _Unit | None:
        async with self.ctx.session_factory() as session:
            first = await self.queue.claim(session, limit=1)
            if not first:
                await session.rollback()
                return None
            job = first[0]
            siblings = await self.queue.claim(
                session,
                limit=MAX_JOBS_PER_ASSET,
                filters=[SnapshotJob.source_asset_id == job.source_asset_id],
            )
            jobs = [job, *siblings]
            asset = await session.get(ContentAsset, job.source_asset_id)
            if asset is None or not asset.storage_key:
                for item in jobs:
                    JobQueue.fail(item, "Source asset no longer exists.", retryable=False)
                await session.commit()
                return None
            unit = _Unit(
                asset=SourceAsset(
                    id=asset.id,
                    content_object_id=job.content_object_id,
                    media_type=asset.media_type,
                    mime_type=asset.mime_type,
                    filename=asset.filename,
                    storage_key=asset.storage_key,
                    text_content=asset.text_content,
                ),
                owner_user_id=job.owner_user_id,
                correlation_id=job.correlation_id,
                job_ids={item.job_type: item.id for item in jobs},
            )
            await session.commit()
        unit.artifact_ids = {job_type: str(uuid4()) for job_type in unit.job_ids}
        return unit

    # --- process -------------------------------------------------------------------------
    async def _process(self, unit: _Unit) -> None:
        log = logger.bind(asset_id=unit.asset.id, job_types=sorted(unit.job_ids))
        work_dir = tempfile.TemporaryDirectory(prefix="seyvix-snapshot-")
        try:
            try:
                async with asyncio.timeout(self.job_budget_seconds):
                    outcomes = await self.generator.generate(
                        unit.asset, unit.job_ids, Path(work_dir.name),
                        artifact_ids=unit.artifact_ids,
                    )  # fmt: skip
            except TimeoutError:
                outcomes = {
                    job_type: SnapshotError("Snapshot timed out.", retryable=True)
                    for job_type in unit.job_ids
                }
            stored = await self._upload(unit, outcomes)
            stale = await self._finalize(unit, stored)
            await self._delete_prefixes(stale)
            log.info(
                "snapshot.unit.done",
                results={
                    job_type: "ok" if isinstance(result, _Stored) else str(result)[:200]
                    for job_type, result in stored.items()
                },
            )
        except asyncio.CancelledError:
            await asyncio.shield(self._release(unit))
            raise
        finally:
            await asyncio.to_thread(work_dir.cleanup)

    async def _upload(
        self, unit: _Unit, outcomes: dict[str, Outcome]
    ) -> dict[str, _Stored | SnapshotError]:
        storage = self.ctx.storage
        results: dict[str, _Stored | SnapshotError] = {}
        for job_type, outcome in outcomes.items():
            if isinstance(outcome, SnapshotError):
                results[job_type] = outcome
                continue
            artifact_id = unit.artifact_ids[job_type]
            if outcome.path is None:
                text = outcome.text or ""
                results[job_type] = _Stored(outcome, artifact_id, None, len(text.encode()), None)
                continue
            key = asset_artifact_key(
                unit.asset.storage_key, job_type, artifact_id, outcome.filename
            )
            try:
                put = await storage.put_file(key, outcome.path, outcome.mime_type)
                if outcome.resources_dir is not None:
                    for resource in await asyncio.to_thread(_list_files, outcome.resources_dir):
                        await storage.put_file(
                            asset_artifact_key(
                                unit.asset.storage_key,
                                job_type,
                                artifact_id,
                                "resources",
                                resource.name,
                            ),
                            resource,
                            mime_for_resource(resource.name),
                        )
            except (StorageError, OSError) as exc:
                logger.warning("snapshot.upload.failed", key=key, error=str(exc))
                await self._delete_prefixes([artifact_dir(key)])
                results[job_type] = SnapshotError(f"Storage upload failed: {exc}", retryable=True)
                continue
            results[job_type] = _Stored(outcome, artifact_id, put.key, put.size_bytes, put.checksum)
        return results

    async def _finalize(
        self, unit: _Unit, results: dict[str, _Stored | SnapshotError]
    ) -> list[str]:
        """Apply results in one short transaction; returns storage prefixes to delete."""
        to_delete: list[str] = []
        async with self.ctx.session_factory() as session:
            jobs = {
                job.job_type: job
                for job in await session.scalars(
                    select(SnapshotJob)
                    .where(SnapshotJob.id.in_(list(unit.job_ids.values())))
                    .with_for_update()
                )
            }
            changed = False
            markdown_settled: SnapshotJob | None = None
            content_object_id = unit.asset.content_object_id
            for job_type, result in results.items():
                job = jobs.get(job_type)
                owned = (
                    job is not None
                    and job.status == JOB_PROCESSING
                    and job.locked_by == self.queue.worker_id
                )
                if job is None or not owned:
                    # Re-queued (source changed / reprocess) or deleted while we worked.
                    if isinstance(result, _Stored) and result.key is not None:
                        to_delete.append(artifact_dir(result.key))
                    continue
                content_object_id = job.content_object_id
                if isinstance(result, _Stored):
                    to_delete.extend(await self._replace_artifact(session, job, result))
                    job.metadata_ = dict(result.generated.metadata)
                    JobQueue.succeed(job)
                    changed = True
                else:
                    JobQueue.fail(job, str(result), retryable=result.retryable)
                    changed = changed or job.status != JOB_PENDING
                if job_type == "markdown" and job.status != JOB_PENDING:
                    markdown_settled = job
            await session.flush()
            if markdown_settled is not None:
                markdown = results.get("markdown")
                stored = markdown if isinstance(markdown, _Stored) else None
                await publish_text_completed_if_settled(
                    session,
                    content_object_id=content_object_id,
                    owner_user_id=unit.owner_user_id,
                    correlation_id=markdown_settled.correlation_id,
                    asset=unit.asset if stored is not None else None,
                    artifact_id=stored.artifact_id if stored is not None else None,
                    metadata={"job_id": markdown_settled.id},
                )
            if changed:
                await touch_content_objects(session, [content_object_id])
            await session.commit()
        return to_delete

    async def _replace_artifact(
        self, session: AsyncSession, job: SnapshotJob, stored: _Stored
    ) -> list[str]:
        old_keys = list(
            await session.scalars(
                delete(SnapshotArtifact)
                .where(
                    SnapshotArtifact.source_asset_id == job.source_asset_id,
                    SnapshotArtifact.artifact_type == job.job_type,
                )
                .returning(SnapshotArtifact.storage_key)
            )
        )
        generated = stored.generated
        session.add(
            SnapshotArtifact(
                id=stored.artifact_id,
                owner_user_id=job.owner_user_id,
                content_object_id=job.content_object_id,
                source_asset_id=job.source_asset_id,
                artifact_type=job.job_type,
                filename=generated.filename,
                mime_type=generated.mime_type,
                size_bytes=stored.size_bytes,
                storage_key=stored.key,
                checksum=stored.checksum,
                text_content=generated.text,
            )
        )
        return [artifact_dir(key) for key in old_keys if key and key != stored.key]

    async def _release(self, unit: _Unit) -> None:
        """Shutdown mid-job: hand the jobs back without burning an attempt."""
        try:
            async with self.ctx.session_factory() as session:
                await session.execute(
                    update(SnapshotJob)
                    .where(
                        SnapshotJob.id.in_(list(unit.job_ids.values())),
                        SnapshotJob.status == JOB_PROCESSING,
                        SnapshotJob.locked_by == self.queue.worker_id,
                    )
                    .values(
                        status=JOB_PENDING,
                        attempts=func.greatest(SnapshotJob.attempts - 1, 0),
                        locked_at=None,
                        locked_by=None,
                    )
                )
                await session.commit()
        except Exception:  # noqa: BLE001 - the lease expiry recovers the jobs anyway
            logger.warning("snapshot.release.failed", asset_id=unit.asset.id, exc_info=True)

    async def _delete_prefixes(self, prefixes: list[str]) -> None:
        for prefix in prefixes:
            try:
                await self.ctx.storage.delete_prefix(prefix)
            except StorageError:
                logger.warning("snapshot.storage.cleanup_failed", prefix=prefix, exc_info=True)


def _list_files(directory: Path) -> list[Path]:
    return sorted(path for path in directory.iterdir() if path.is_file())
