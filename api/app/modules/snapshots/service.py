from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.content.models import ContentAsset, ContentObject
from app.modules.snapshots.infrastructure.repositories import (
    SnapshotArtifactRepository,
    SnapshotJobRepository,
    SnapshotSettingsRepository,
)
from app.modules.snapshots.models import SnapshotUserSettings
from app.modules.snapshots.schemas import (
    SnapshotArtifactListResponse,
    SnapshotArtifactResponse,
    SnapshotFormatOverrides,
    SnapshotFormatSettings,
    SnapshotJobListResponse,
    SnapshotJobResponse,
    SnapshotSettingsResponse,
    UpdateSnapshotSettingsRequest,
)
from app.platform.storage.service import LocalVolumeStorage, StorageBackend

SNAPSHOT_JOB_TYPES = (
    "thumbnail",
    "thumbnail_text",
    "markdown",
    "screenshot",
    "webpage_html",
    "pdf",
    "archive_org",
)

MARKDOWN_SUFFIXES = {".md", ".markdown"}
OFFICE_PDF_SUFFIXES = {
    ".doc",
    ".docx",
    ".odp",
    ".ods",
    ".odt",
    ".ppt",
    ".pptx",
    ".rtf",
    ".xls",
    ".xlsx",
}
OFFICE_PDF_MIME_TYPES = {
    "application/msword",
    "application/rtf",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "application/vnd.oasis.opendocument.presentation",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
TEXT_PDF_SUFFIXES = {".csv", ".htm", ".html", ".json", ".txt"}
TEXT_PDF_MIME_TYPES = {
    "application/json",
    "text/csv",
    "text/html",
    "text/markdown",
    "text/plain",
}
TEXT_THUMBNAIL_SUFFIXES = {".md", ".markdown", ".txt"}


@dataclass(slots=True)
class EffectiveSnapshotSettings:
    screenshot: bool
    webpage_html: bool
    pdf: bool
    markdown: bool
    archive_org: bool


@dataclass(frozen=True, slots=True)
class SnapshotArtifactReference:
    url: str
    filename: str
    mime_type: str
    size_bytes: int


class SnapshotArtifactNotFoundError(Exception):
    pass


def plan_snapshot_job_types(
    asset: ContentAsset,
    effective: EffectiveSnapshotSettings,
) -> tuple[str, ...]:
    job_types: list[str] = ["thumbnail_text" if _uses_text_thumbnail(asset) else "thumbnail"]

    if effective.markdown and not _is_markdown_asset(asset):
        job_types.append("markdown")
    if effective.pdf and _should_generate_pdf(asset):
        job_types.append("pdf")
    if _is_site_asset(asset):
        if effective.screenshot:
            job_types.append("screenshot")
        if effective.webpage_html:
            job_types.append("webpage_html")

    return tuple(job_types)


class SnapshotService:
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
        self.settings = SnapshotSettingsRepository(session)
        self.jobs = SnapshotJobRepository(session)
        self.artifacts = SnapshotArtifactRepository(session)
        self.api_prefix = get_settings().api_prefix

    async def get_user_settings(self, owner_user_id: str) -> SnapshotSettingsResponse:
        stored = await self.settings.get(owner_user_id)
        effective = self._effective_settings(stored)
        return SnapshotSettingsResponse(
            effective=SnapshotFormatSettings(
                screenshot=effective.screenshot,
                webpage_html=effective.webpage_html,
                pdf=effective.pdf,
                markdown=effective.markdown,
                archive_org=effective.archive_org,
            ),
            overrides=self._overrides(stored),
        )

    async def update_user_settings(
        self,
        *,
        owner_user_id: str,
        payload: UpdateSnapshotSettingsRequest,
    ) -> SnapshotSettingsResponse:
        stored = await self.settings.get_or_create(owner_user_id)

        update = payload.model_dump(exclude_unset=True)
        if "screenshot" in update:
            stored.archive_as_screenshot = payload.screenshot
        if "webpage_html" in update:
            stored.archive_as_webpage_html = payload.webpage_html
        if "pdf" in update:
            stored.archive_as_pdf = payload.pdf
        if "markdown" in update:
            stored.archive_as_markdown = payload.markdown
        if "archive_org" in update:
            stored.archive_as_archive_org = payload.archive_org

        await self.session.commit()
        return await self.get_user_settings(owner_user_id)

    async def list_jobs(
        self,
        *,
        owner_user_id: str,
        content_object_id: str | None,
    ) -> SnapshotJobListResponse:
        jobs = await self.jobs.list_for_user(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
        )
        return SnapshotJobListResponse(
            items=[
                SnapshotJobResponse(
                    id=job.id,
                    content_object_id=job.content_object_id,
                    source_asset_id=job.source_asset_id,
                    job_type=job.job_type,
                    status=job.status,
                    attempts=job.attempts,
                    error_message=job.error_message,
                )
                for job in jobs
            ]
        )

    async def list_artifacts(
        self,
        *,
        owner_user_id: str,
        content_object_id: str | None,
    ) -> SnapshotArtifactListResponse:
        artifacts = await self.artifacts.list_for_user(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
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
                    status=artifact.status,
                    url=f"{self.api_prefix}/snapshots/artifacts/{artifact.id}",
                )
                for artifact in artifacts
            ]
        )

    async def get_artifact_file(
        self,
        *,
        owner_user_id: str,
        artifact_id: str,
    ) -> tuple[Path, str, str]:
        artifact = await self.artifacts.get_for_user(
            owner_user_id=owner_user_id,
            artifact_id=artifact_id,
        )
        if artifact is None:
            raise SnapshotArtifactNotFoundError
        path = self.storage_root / artifact.storage_path
        if not path.exists():
            temp_file = NamedTemporaryFile(prefix=f"{artifact.id}-", delete=False)
            temp_file.write(
                self.storage_backend.get_bytes(artifact.storage_key or artifact.storage_path)
            )
            temp_file.close()
            path = Path(temp_file.name)
        return path, artifact.mime_type, artifact.filename

    async def enqueue_for_content_object(
        self,
        content_object: ContentObject,
        *,
        correlation_id: str | None = None,
        source_event_id: str | None = None,
    ) -> None:
        stored = await self.settings.get(content_object.owner_user_id)
        effective = self._effective_settings(stored)
        source_assets = [asset for asset in content_object.assets if asset.role == "original"]

        for asset in source_assets:
            for job_type in plan_snapshot_job_types(asset, effective):
                await self._enqueue_job(
                    content_object,
                    asset,
                    job_type,
                    correlation_id=correlation_id,
                    source_event_id=source_event_id,
                )

        if effective.archive_org and self._is_site_object(content_object):
            await self._enqueue_job(
                content_object,
                None,
                "archive_org",
                correlation_id=correlation_id,
                source_event_id=source_event_id,
            )

    async def get_thumbnail_path(self, *, source_asset_id: str) -> tuple[Path, str] | None:
        artifact = await self.artifacts.get_ready(
            source_asset_id=source_asset_id,
            artifact_type="thumbnail",
        )
        if artifact is None:
            return None
        path = self.storage_root / artifact.storage_path
        if not path.exists():
            temp_file = NamedTemporaryFile(prefix=f"{artifact.id}-", delete=False)
            temp_file.write(
                self.storage_backend.get_bytes(artifact.storage_key or artifact.storage_path)
            )
            temp_file.close()
            path = Path(temp_file.name)
        return path, artifact.mime_type

    async def get_asset_artifact_references(
        self,
        *,
        source_asset_id: str,
    ) -> dict[str, SnapshotArtifactReference]:
        artifacts = await self.artifacts.list_ready_for_asset(source_asset_id=source_asset_id)
        return {
            artifact.artifact_type: SnapshotArtifactReference(
                url=f"{self.api_prefix}/snapshots/artifacts/{artifact.id}",
                filename=artifact.filename,
                mime_type=artifact.mime_type,
                size_bytes=artifact.size_bytes,
            )
            for artifact in artifacts
        }

    async def get_thumbnail_text(
        self,
        *,
        source_asset_id: str,
        max_chars: int = 5000,
    ) -> str | None:
        artifact = await self.artifacts.get_ready(
            source_asset_id=source_asset_id,
            artifact_type="thumbnail_text",
        )
        if artifact is None:
            return None
        path = self.storage_root / artifact.storage_path
        if path.exists():
            data = path.read_bytes()
        else:
            data = self.storage_backend.get_bytes(artifact.storage_key or artifact.storage_path)
        return data.decode("utf-8", errors="replace")[:max_chars]

    async def is_thumbnail_unavailable(self, *, source_asset_id: str) -> bool:
        job = await self.jobs.get_for_asset(source_asset_id=source_asset_id, job_type="thumbnail")
        if job is not None:
            return job.status == "failed"

        text_job = await self.jobs.get_for_asset(
            source_asset_id=source_asset_id,
            job_type="thumbnail_text",
        )
        return text_job is not None and text_job.status in {"done", "failed"}

    async def _enqueue_job(
        self,
        content_object: ContentObject,
        asset: ContentAsset | None,
        job_type: str,
        correlation_id: str | None = None,
        source_event_id: str | None = None,
    ) -> None:
        await self.jobs.add_once(
            owner_user_id=content_object.owner_user_id,
            content_object_id=content_object.id,
            source_asset_id=asset.id if asset is not None else None,
            job_type=job_type,
            status="pending",
            correlation_id=correlation_id,
            source_event_id=source_event_id,
        )

    @staticmethod
    def _is_site_object(content_object: ContentObject) -> bool:
        return content_object.media_type == "link"

    @staticmethod
    def _overrides(stored: SnapshotUserSettings | None) -> SnapshotFormatOverrides:
        if stored is None:
            return SnapshotFormatOverrides()
        return SnapshotFormatOverrides(
            screenshot=stored.archive_as_screenshot,
            webpage_html=stored.archive_as_webpage_html,
            pdf=stored.archive_as_pdf,
            markdown=stored.archive_as_markdown,
            archive_org=stored.archive_as_archive_org,
        )

    @staticmethod
    def _effective_settings(
        stored: SnapshotUserSettings | None,
    ) -> EffectiveSnapshotSettings:
        settings = get_settings()
        return EffectiveSnapshotSettings(
            screenshot=(
                stored.archive_as_screenshot
                if stored is not None and stored.archive_as_screenshot is not None
                else settings.snapshot_archive_screenshot_enabled
            ),
            webpage_html=(
                stored.archive_as_webpage_html
                if stored is not None and stored.archive_as_webpage_html is not None
                else settings.snapshot_archive_webpage_html_enabled
            ),
            pdf=(
                stored.archive_as_pdf
                if stored is not None and stored.archive_as_pdf is not None
                else settings.snapshot_archive_pdf_enabled
            ),
            markdown=(
                stored.archive_as_markdown
                if stored is not None and stored.archive_as_markdown is not None
                else settings.snapshot_archive_markdown_enabled
            ),
            archive_org=(
                stored.archive_as_archive_org
                if stored is not None and stored.archive_as_archive_org is not None
                else settings.snapshot_archive_org_enabled
            ),
        )


def _uses_text_thumbnail(asset: ContentAsset) -> bool:
    suffix = Path(asset.filename).suffix.lower()
    return (
        asset.media_type == "text"
        or asset.mime_type in {"text/markdown", "text/plain"}
        or suffix in TEXT_THUMBNAIL_SUFFIXES
    )


def _is_markdown_asset(asset: ContentAsset) -> bool:
    suffix = Path(asset.filename).suffix.lower()
    return asset.mime_type == "text/markdown" or suffix in MARKDOWN_SUFFIXES


def _should_generate_pdf(asset: ContentAsset) -> bool:
    suffix = Path(asset.filename).suffix.lower()
    if asset.mime_type == "application/pdf" or suffix == ".pdf":
        return False
    if asset.mime_type in OFFICE_PDF_MIME_TYPES:
        return True
    if asset.mime_type in TEXT_PDF_MIME_TYPES:
        return True
    if asset.media_type == "document":
        return suffix in OFFICE_PDF_SUFFIXES | TEXT_PDF_SUFFIXES
    if asset.media_type == "text":
        return suffix in MARKDOWN_SUFFIXES | TEXT_PDF_SUFFIXES
    return _is_site_asset(asset)


def _is_site_asset(asset: ContentAsset) -> bool:
    return asset.media_type == "link"
