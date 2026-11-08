"""Snapshot API service plus the helpers other modules use to read snapshot results.

Scheduling (`schedule_content_object`) runs inside the worker's event handler; processing
lives in `app.modules.snapshots.worker`. Nothing here touches Chromium, LibreOffice or AI.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Final
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.modules.content.models import ContentAsset, ContentObject
from app.modules.snapshots.models import SnapshotArtifact, SnapshotJob, SnapshotUserSettings
from app.modules.snapshots.planning import (
    AssetFacts,
    SnapshotJobType,
    effective_settings,
    plan_snapshot_job_types,
    source_fingerprint,
    text_extractable,
)
from app.modules.snapshots.rewriter import mime_for_resource
from app.modules.snapshots.schemas import (
    ReprocessSnapshotsRequest,
    ReprocessSnapshotsResponse,
    SnapshotArtifactListResponse,
    SnapshotArtifactResponse,
    SnapshotFormatOption,
    SnapshotFormatOverrides,
    SnapshotFormatSettings,
    SnapshotJobListResponse,
    SnapshotJobResponse,
    SnapshotSettingsResponse,
    UpdateSnapshotSettingsRequest,
)
from app.platform.jobs import (
    JOB_CANCELLED,
    JOB_FAILED,
    JOB_PENDING,
    JOB_SUCCEEDED,
    utcnow,
)
from app.platform.storage.service import StorageBackend, StorageObjectNotFoundError

logger = get_logger(__name__)

THUMBNAIL_TEXT_MAX_CHARS: Final = 5000
PRIORITY_AUTOMATIC: Final = 100
PRIORITY_USER: Final = 200
# Job status values exposed by the REST API (the web client predates JOB_* names).
API_JOB_STATUS: Final = {JOB_SUCCEEDED: "done"}
RESOURCE_NAME_RE: Final = re.compile(r"^r\d{4}\.[a-z0-9]{1,8}$")

FORMAT_OPTIONS: Final = (
    ("screenshot", "Screenshot", "Visual webpage screenshot for link materials."),
    ("webpage_html", "HTML archive", "Stored HTML copy of a linked webpage."),
    ("pdf", "PDF", "PDF representation for documents, text files, and links."),
    ("markdown", "Markdown", "Markdown text extracted from supported files and webpages."),
)


class SnapshotNotFoundError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class SnapshotFile:
    """A servable artifact. `key` is set for stored files; `text` for inline text artifacts."""

    key: str | None
    mime_type: str
    filename: str
    size_bytes: int
    text: str | None = None


@dataclass(frozen=True, slots=True)
class SnapshotArtifactReference:
    url: str
    filename: str
    mime_type: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class AssetPreview:
    has_thumbnail: bool = False
    thumbnail_text: str | None = None


def artifact_dir(storage_key: str) -> str:
    """Storage prefix (ending with `/`) holding an artifact file and its resources."""
    return storage_key.rsplit("/", 1)[0] + "/"


def api_job_status(status: str) -> str:
    return API_JOB_STATUS.get(status, status)


class SnapshotService:
    def __init__(
        self,
        session: AsyncSession,
        storage: StorageBackend,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.storage = storage
        self.settings = settings or get_settings()
        self.api_prefix = self.settings.api_prefix

    # --- settings ------------------------------------------------------------------------
    async def get_user_settings(self, owner_user_id: str) -> SnapshotSettingsResponse:
        stored = await self.session.get(SnapshotUserSettings, owner_user_id)
        return self._settings_response(stored)

    async def update_user_settings(
        self, *, owner_user_id: str, payload: UpdateSnapshotSettingsRequest
    ) -> SnapshotSettingsResponse:
        await self.session.execute(
            pg_insert(SnapshotUserSettings)
            .values(owner_user_id=owner_user_id, created_at=utcnow(), updated_at=utcnow())
            .on_conflict_do_nothing(index_elements=[SnapshotUserSettings.owner_user_id])
        )
        stored = await self.session.get(
            SnapshotUserSettings, owner_user_id, with_for_update=True, populate_existing=True
        )
        if stored is None:  # pragma: no cover - the row was inserted above
            raise SnapshotNotFoundError
        update_values = payload.model_dump(exclude_unset=True)
        for key in ("screenshot", "webpage_html", "pdf", "markdown"):
            if key in update_values:
                setattr(stored, f"archive_as_{key}", update_values[key])
        await self.session.commit()
        return self._settings_response(stored)

    def _settings_response(self, stored: SnapshotUserSettings | None) -> SnapshotSettingsResponse:
        effective = effective_settings(self.settings, stored)
        server = effective_settings(self.settings, None)
        return SnapshotSettingsResponse(
            available=[
                SnapshotFormatOption(
                    key=key,
                    label=label,
                    description=description,
                    server_enabled=getattr(server, key),
                )
                for key, label, description in FORMAT_OPTIONS
            ],
            effective=SnapshotFormatSettings(
                screenshot=effective.screenshot,
                webpage_html=effective.webpage_html,
                pdf=effective.pdf,
                markdown=effective.markdown,
            ),
            overrides=SnapshotFormatOverrides(
                screenshot=stored.archive_as_screenshot if stored else None,
                webpage_html=stored.archive_as_webpage_html if stored else None,
                pdf=stored.archive_as_pdf if stored else None,
                markdown=stored.archive_as_markdown if stored else None,
            ),
        )

    # --- listing -------------------------------------------------------------------------
    async def list_jobs(
        self, *, owner_user_id: str, content_object_id: str | None
    ) -> SnapshotJobListResponse:
        query = select(SnapshotJob).where(SnapshotJob.owner_user_id == owner_user_id)
        if content_object_id is not None:
            query = query.where(SnapshotJob.content_object_id == content_object_id)
        jobs = await self.session.scalars(query.order_by(SnapshotJob.created_at.asc()).limit(500))
        return SnapshotJobListResponse(
            items=[
                SnapshotJobResponse(
                    id=job.id,
                    content_object_id=job.content_object_id,
                    source_asset_id=job.source_asset_id,
                    job_type=job.job_type,
                    status=api_job_status(job.status),
                    attempts=job.attempts,
                    error_message=job.last_error,
                )
                for job in jobs
            ]
        )

    async def list_artifacts(
        self, *, owner_user_id: str, content_object_id: str | None
    ) -> SnapshotArtifactListResponse:
        query = select(SnapshotArtifact).where(SnapshotArtifact.owner_user_id == owner_user_id)
        if content_object_id is not None:
            query = query.where(SnapshotArtifact.content_object_id == content_object_id)
        artifacts = await self.session.scalars(
            query.order_by(SnapshotArtifact.created_at.asc()).limit(500)
        )
        return SnapshotArtifactListResponse(
            items=[
                SnapshotArtifactResponse(
                    id=artifact.id,
                    content_object_id=artifact.content_object_id,
                    source_asset_id=artifact.source_asset_id,
                    artifact_type=artifact.artifact_type,
                    filename=artifact.filename,
                    mime_type=artifact.mime_type,
                    size_bytes=artifact.size_bytes,
                    status="ready",
                    url=self._artifact_url(artifact.id),
                )
                for artifact in artifacts
            ]
        )

    # --- reprocessing --------------------------------------------------------------------
    async def reprocess(
        self, *, owner_user_id: str, payload: ReprocessSnapshotsRequest
    ) -> ReprocessSnapshotsResponse:
        query = (
            select(ContentAsset, ContentObject.owner_user_id)
            .join(ContentObject, ContentObject.id == ContentAsset.content_object_id)
            .where(ContentObject.owner_user_id == owner_user_id)
        )
        if payload.source_asset_id is not None:
            query = query.where(ContentAsset.id == payload.source_asset_id)
            if payload.content_object_id is not None:
                query = query.where(ContentAsset.content_object_id == payload.content_object_id)
        elif payload.content_object_id is not None:
            query = query.where(
                ContentAsset.content_object_id == payload.content_object_id,
                ContentAsset.role == "original",
            )
        else:
            raise SnapshotNotFoundError
        rows = (await self.session.execute(query)).all()
        if not rows:
            raise SnapshotNotFoundError

        job_types: list[SnapshotJobType] = list(dict.fromkeys(payload.job_types or ["markdown"]))
        assets = [asset for asset, _ in rows]
        await queue_jobs(
            self.session,
            [
                _job_row(asset, owner_user_id, job_type, priority=PRIORITY_USER)
                for asset in assets
                for job_type in job_types
            ],
            force=payload.force,
        )
        job_ids = list(
            await self.session.scalars(
                select(SnapshotJob.id).where(
                    SnapshotJob.source_asset_id.in_([asset.id for asset in assets]),
                    SnapshotJob.job_type.in_(job_types),
                )
            )
        )
        await self.session.commit()
        return ReprocessSnapshotsResponse(
            queued_count=len(job_ids),
            job_ids=job_ids,
            source_asset_ids=[asset.id for asset in assets],
        )

    # --- files ---------------------------------------------------------------------------
    async def get_artifact_file(self, *, owner_user_id: str, artifact_id: str) -> SnapshotFile:
        artifact = await self._owned_artifact(owner_user_id, artifact_id)
        return _snapshot_file(artifact)

    async def get_artifact_resource(
        self, *, owner_user_id: str, artifact_id: str, filename: str
    ) -> SnapshotFile:
        if not RESOURCE_NAME_RE.fullmatch(filename):
            raise SnapshotNotFoundError
        artifact = await self._owned_artifact(owner_user_id, artifact_id)
        if artifact.artifact_type != "webpage_html" or artifact.storage_key is None:
            raise SnapshotNotFoundError
        key = f"{artifact_dir(artifact.storage_key)}resources/{filename}"
        try:
            info = await self.storage.stat(key)
        except StorageObjectNotFoundError as exc:
            raise SnapshotNotFoundError from exc
        return SnapshotFile(
            key=key,
            mime_type=mime_for_resource(filename),
            filename=filename,
            size_bytes=info.size_bytes,
        )

    async def get_thumbnail(self, *, source_asset_id: str) -> SnapshotFile | None:
        artifact = await self._artifact(source_asset_id, "thumbnail")
        return _snapshot_file(artifact) if artifact is not None else None

    async def is_thumbnail_unavailable(self, *, source_asset_id: str) -> bool:
        """True when no image thumbnail will ever appear for this asset (until reprocessed)."""
        statuses = dict(
            (
                await self.session.execute(
                    select(SnapshotJob.job_type, SnapshotJob.status).where(
                        SnapshotJob.source_asset_id == source_asset_id,
                        SnapshotJob.job_type.in_(("thumbnail", "thumbnail_text")),
                    )
                )
            ).tuples()
        )
        if "thumbnail" in statuses:
            return statuses["thumbnail"] in {JOB_FAILED, JOB_CANCELLED}
        return statuses.get("thumbnail_text") in {JOB_SUCCEEDED, JOB_FAILED, JOB_CANCELLED}

    async def get_asset_artifact_references(
        self, *, source_asset_id: str
    ) -> dict[str, SnapshotArtifactReference]:
        return (await self.asset_artifact_references([source_asset_id])).get(source_asset_id, {})

    async def asset_artifact_references(
        self, asset_ids: Iterable[str]
    ) -> dict[str, dict[str, SnapshotArtifactReference]]:
        ids = list(dict.fromkeys(asset_ids))
        if not ids:
            return {}
        rows = await self.session.execute(
            select(
                SnapshotArtifact.id,
                SnapshotArtifact.source_asset_id,
                SnapshotArtifact.artifact_type,
                SnapshotArtifact.filename,
                SnapshotArtifact.mime_type,
                SnapshotArtifact.size_bytes,
            ).where(SnapshotArtifact.source_asset_id.in_(ids))
        )
        references: dict[str, dict[str, SnapshotArtifactReference]] = {}
        for artifact_id, asset_id, artifact_type, filename, mime_type, size in rows.tuples():
            references.setdefault(asset_id, {})[artifact_type] = SnapshotArtifactReference(
                url=self._artifact_url(artifact_id),
                filename=filename,
                mime_type=mime_type,
                size_bytes=size,
            )
        return references

    async def asset_previews(
        self, *, owner_user_id: str, asset_ids: Iterable[str]
    ) -> dict[str, AssetPreview]:
        """Card previews for many assets in one query (no storage reads)."""
        ids = list(dict.fromkeys(asset_ids))
        if not ids:
            return {}
        rows = await self.session.execute(
            select(
                SnapshotArtifact.source_asset_id,
                SnapshotArtifact.artifact_type,
                SnapshotArtifact.text_content,
            ).where(
                SnapshotArtifact.owner_user_id == owner_user_id,
                SnapshotArtifact.source_asset_id.in_(ids),
                SnapshotArtifact.artifact_type.in_(("thumbnail", "thumbnail_text")),
            )
        )
        previews: dict[str, AssetPreview] = {}
        for asset_id, artifact_type, text in rows.tuples():
            current = previews.get(asset_id, AssetPreview())
            if artifact_type == "thumbnail":
                previews[asset_id] = AssetPreview(True, current.thumbnail_text)
            else:
                previews[asset_id] = AssetPreview(current.has_thumbnail, text)
        return previews

    async def get_thumbnail_text(
        self, *, source_asset_id: str, max_chars: int = THUMBNAIL_TEXT_MAX_CHARS
    ) -> str | None:
        text = await self.session.scalar(
            select(SnapshotArtifact.text_content).where(
                SnapshotArtifact.source_asset_id == source_asset_id,
                SnapshotArtifact.artifact_type == "thumbnail_text",
            )
        )
        return text[:max_chars] if text else None

    async def get_markdown_text(
        self, *, source_asset_id: str, max_chars: int = 50_000
    ) -> str | None:
        key = await self.session.scalar(
            select(SnapshotArtifact.storage_key).where(
                SnapshotArtifact.source_asset_id == source_asset_id,
                SnapshotArtifact.artifact_type == "markdown",
            )
        )
        if key is None:
            return None
        chunks: list[bytes] = []
        try:
            # UTF-8 needs at most 4 bytes per character: never read more than needed.
            async for chunk in self.storage.iter_bytes(key, 0, max_chars * 4):
                chunks.append(chunk)
        except StorageObjectNotFoundError:
            logger.warning("snapshots.markdown.missing", source_asset_id=source_asset_id, key=key)
            return None
        text = b"".join(chunks).decode("utf-8", errors="ignore").strip()
        return text[:max_chars] or None

    # --- internals -----------------------------------------------------------------------
    def _artifact_url(self, artifact_id: str) -> str:
        return f"{self.api_prefix}/snapshots/artifacts/{artifact_id}"

    async def _artifact(self, source_asset_id: str, artifact_type: str) -> SnapshotArtifact | None:
        value: SnapshotArtifact | None = await self.session.scalar(
            select(SnapshotArtifact).where(
                SnapshotArtifact.source_asset_id == source_asset_id,
                SnapshotArtifact.artifact_type == artifact_type,
            )
        )
        return value

    async def _owned_artifact(self, owner_user_id: str, artifact_id: str) -> SnapshotArtifact:
        artifact = await self.session.get(SnapshotArtifact, artifact_id)
        if artifact is None or artifact.owner_user_id != owner_user_id:
            raise SnapshotNotFoundError
        return artifact


def _snapshot_file(artifact: SnapshotArtifact) -> SnapshotFile:
    return SnapshotFile(
        key=artifact.storage_key,
        mime_type=artifact.mime_type,
        filename=artifact.filename,
        size_bytes=artifact.size_bytes,
        text=artifact.text_content if artifact.storage_key is None else None,
    )


# --- scheduling (used by the worker's event handler and by reprocess) -----------------------
def _job_row(
    asset: ContentAsset,
    owner_user_id: str,
    job_type: SnapshotJobType,
    *,
    priority: int,
    correlation_id: str | None = None,
    source_event_id: str | None = None,
) -> dict[str, Any]:
    now = utcnow()
    return {
        "id": str(uuid4()),
        "owner_user_id": owner_user_id,
        "content_object_id": asset.content_object_id,
        "source_asset_id": asset.id,
        "job_type": job_type,
        "source_fingerprint": source_fingerprint(
            storage_key=asset.storage_key or "",
            size_bytes=asset.size_bytes,
            checksum=asset.checksum,
            text_content=asset.text_content,
        ),
        "correlation_id": correlation_id,
        "source_event_id": source_event_id,
        "metadata": {},
        "status": JOB_PENDING,
        "priority": priority,
        "attempts": 0,
        "max_attempts": get_settings().worker_max_job_attempts,
        "run_after": now,
        "created_at": now,
        "updated_at": now,
    }


async def queue_jobs(session: AsyncSession, rows: Sequence[dict[str, Any]], *, force: bool) -> None:
    """Insert jobs; an existing job is re-queued when `force`, when its source changed, or
    when it previously failed. Unchanged done/pending jobs are left alone, so duplicate or
    unrelated update events never cause duplicate work."""
    if not rows:
        return
    # Table (not ORM entity) insert: row keys are column names (`metadata` would otherwise
    # resolve to the declarative `Base.metadata`).
    statement = pg_insert(SnapshotJob.__table__).values(rows)  # type: ignore[arg-type]
    excluded = statement.excluded
    table = SnapshotJob.__table__.c
    statement = statement.on_conflict_do_update(
        constraint="uq_snapshot_jobs_asset_type",
        set_={
            "status": JOB_PENDING,
            "attempts": 0,
            "run_after": excluded.run_after,
            "locked_at": None,
            "locked_by": None,
            "last_error": None,
            "priority": excluded.priority,
            "content_object_id": excluded.content_object_id,
            "source_fingerprint": excluded.source_fingerprint,
            "correlation_id": excluded.correlation_id,
            "source_event_id": excluded.source_event_id,
            "updated_at": excluded.updated_at,
        },
        where=None
        if force
        else or_(
            table.source_fingerprint.is_distinct_from(excluded.source_fingerprint),
            table.status.in_((JOB_FAILED, JOB_CANCELLED)),
        ),
    )
    await session.execute(statement)


async def schedule_content_object(
    session: AsyncSession,
    content_object_id: str,
    *,
    correlation_id: str | None = None,
    source_event_id: str | None = None,
) -> int | None:
    """Plan and queue snapshot jobs for every original asset of a content object.
    Returns the number of planned jobs, or None when the object no longer exists."""
    row = (
        await session.execute(
            select(ContentObject.owner_user_id, ContentObject.media_type, SnapshotUserSettings)
            .outerjoin(
                SnapshotUserSettings,
                SnapshotUserSettings.owner_user_id == ContentObject.owner_user_id,
            )
            .where(ContentObject.id == content_object_id)
        )
    ).first()
    if row is None:
        logger.info("snapshots.schedule.object_missing", content_object_id=content_object_id)
        return None
    owner_user_id, object_media_type, stored = row
    assets = list(
        await session.scalars(
            select(ContentAsset).where(
                ContentAsset.content_object_id == content_object_id,
                ContentAsset.role == "original",
            )
        )
    )
    settings = get_settings()
    effective = effective_settings(settings, stored)
    rows: list[dict[str, Any]] = []
    for asset in assets:
        # A link note's non-link assets are note metadata, not a site to snapshot.
        if object_media_type == "link" and asset.media_type != "link":
            continue
        facts = AssetFacts(asset.media_type, asset.mime_type, asset.filename)
        rows.extend(
            _job_row(
                asset,
                owner_user_id,
                job_type,
                priority=PRIORITY_AUTOMATIC,
                correlation_id=correlation_id,
                source_event_id=source_event_id,
            )
            for job_type in plan_snapshot_job_types(
                facts, effective, extract_text=text_extractable(facts, settings)
            )
        )
    await queue_jobs(session, rows, force=False)
    return len(rows)


async def reassign_asset_snapshots(
    session: AsyncSession, asset_ids: Iterable[str], content_object_id: str
) -> None:
    """Follow assets moved to another content object (merge/collapse). Storage keys stay."""
    ids = list(asset_ids)
    if not ids:
        return
    await session.execute(
        update(SnapshotJob)
        .where(SnapshotJob.source_asset_id.in_(ids))
        .values(content_object_id=content_object_id)
    )
    await session.execute(
        update(SnapshotArtifact)
        .where(SnapshotArtifact.source_asset_id.in_(ids))
        .values(content_object_id=content_object_id)
    )


__all__ = [
    "AssetPreview",
    "SnapshotArtifactReference",
    "SnapshotFile",
    "SnapshotNotFoundError",
    "SnapshotService",
    "artifact_dir",
    "queue_jobs",
    "reassign_asset_snapshots",
    "schedule_content_object",
]
