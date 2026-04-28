from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.content.models import ContentAsset, ContentObject
from app.modules.snapshots.infrastructure.repositories import (
    SnapshotArtifactRepository,
    SnapshotJobRepository,
    SnapshotSettingsRepository,
)
from app.modules.snapshots.models import SnapshotJob, SnapshotUserSettings
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

SNAPSHOT_JOB_TYPES = ("markdown", "screenshot", "webpage_html", "pdf")


@dataclass(slots=True)
class EffectiveSnapshotSettings:
    screenshot: bool
    webpage_html: bool
    pdf: bool
    markdown: bool
    archive_org: bool


class SnapshotArtifactNotFoundError(Exception):
    pass


class SnapshotService:
    def __init__(self, session: AsyncSession, storage_root: Path | None = None) -> None:
        self.session = session
        self.storage_root = storage_root or Path("data/content")
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
        stored = await self.settings.get(owner_user_id)
        if stored is None:
            stored = SnapshotUserSettings(owner_user_id=owner_user_id)
            self.settings.add(stored)

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
            raise SnapshotArtifactNotFoundError
        return path, artifact.mime_type, artifact.filename

    async def enqueue_for_content_object(self, content_object: ContentObject) -> None:
        stored = await self.settings.get(content_object.owner_user_id)
        effective = self._effective_settings(stored)
        source_assets = [asset for asset in content_object.assets if asset.role == "original"]

        for asset in source_assets:
            await self._enqueue_job(content_object, asset, "thumbnail")

            if effective.markdown:
                await self._enqueue_job(content_object, asset, "markdown")
            if effective.screenshot:
                await self._enqueue_job(content_object, asset, "screenshot")
            if effective.webpage_html:
                await self._enqueue_job(content_object, asset, "webpage_html")
            if effective.pdf:
                await self._enqueue_job(content_object, asset, "pdf")

        if effective.archive_org:
            await self._enqueue_job(content_object, None, "archive_org")

    async def get_thumbnail_path(self, *, source_asset_id: str) -> tuple[Path, str] | None:
        artifact = await self.artifacts.get_ready(
            source_asset_id=source_asset_id,
            artifact_type="thumbnail",
        )
        if artifact is None:
            return None
        return self.storage_root / artifact.storage_path, artifact.mime_type

    async def _enqueue_job(
        self,
        content_object: ContentObject,
        asset: ContentAsset | None,
        job_type: str,
    ) -> None:
        if await self.jobs.exists(
            content_object_id=content_object.id,
            source_asset_id=asset.id if asset is not None else None,
            job_type=job_type,
        ):
            return
        self.jobs.add(
            SnapshotJob(
                owner_user_id=content_object.owner_user_id,
                content_object_id=content_object.id,
                source_asset_id=asset.id if asset is not None else None,
                job_type=job_type,
                status="pending",
            )
        )

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
