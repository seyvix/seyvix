from __future__ import annotations

from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.content.models import ContentAsset, ContentObject
from app.modules.snapshots.models import SnapshotArtifact, SnapshotJob, SnapshotUserSettings


class SnapshotSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, owner_user_id: str) -> SnapshotUserSettings | None:
        return cast(
            SnapshotUserSettings | None,
            await self.session.scalar(
                select(SnapshotUserSettings).where(
                    SnapshotUserSettings.owner_user_id == owner_user_id
                )
            ),
        )

    def add(self, settings: SnapshotUserSettings) -> None:
        self.session.add(settings)


class SnapshotJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, job: SnapshotJob) -> None:
        self.session.add(job)

    async def exists(
        self,
        *,
        content_object_id: str,
        source_asset_id: str | None,
        job_type: str,
    ) -> bool:
        query = select(SnapshotJob.id).where(
            SnapshotJob.content_object_id == content_object_id,
            SnapshotJob.source_asset_id == source_asset_id,
            SnapshotJob.job_type == job_type,
        )
        return await self.session.scalar(query) is not None

    async def list_pending(self, limit: int) -> list[SnapshotJob]:
        query = (
            select(SnapshotJob)
            .where(SnapshotJob.status == "pending")
            .order_by(SnapshotJob.created_at.asc())
            .limit(limit)
        )
        return list(await self.session.scalars(query))

    async def list_for_user(
        self,
        *,
        owner_user_id: str,
        content_object_id: str | None,
    ) -> list[SnapshotJob]:
        query = select(SnapshotJob).where(SnapshotJob.owner_user_id == owner_user_id)
        if content_object_id is not None:
            query = query.where(SnapshotJob.content_object_id == content_object_id)
        query = query.order_by(SnapshotJob.created_at.asc())
        return list(await self.session.scalars(query))


class SnapshotArtifactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, artifact: SnapshotArtifact) -> None:
        self.session.add(artifact)

    async def get_ready(
        self,
        *,
        source_asset_id: str,
        artifact_type: str,
    ) -> SnapshotArtifact | None:
        query = select(SnapshotArtifact).where(
            SnapshotArtifact.source_asset_id == source_asset_id,
            SnapshotArtifact.artifact_type == artifact_type,
            SnapshotArtifact.status == "ready",
        )
        return cast(SnapshotArtifact | None, await self.session.scalar(query))

    async def list_for_user(
        self,
        *,
        owner_user_id: str,
        content_object_id: str | None,
    ) -> list[SnapshotArtifact]:
        query = select(SnapshotArtifact).where(SnapshotArtifact.owner_user_id == owner_user_id)
        if content_object_id is not None:
            query = query.where(SnapshotArtifact.content_object_id == content_object_id)
        query = query.order_by(SnapshotArtifact.created_at.asc())
        return list(await self.session.scalars(query))

    async def get_for_user(
        self,
        *,
        owner_user_id: str,
        artifact_id: str,
    ) -> SnapshotArtifact | None:
        query = select(SnapshotArtifact).where(
            SnapshotArtifact.owner_user_id == owner_user_id,
            SnapshotArtifact.id == artifact_id,
        )
        return cast(SnapshotArtifact | None, await self.session.scalar(query))


class SnapshotContentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_object(self, content_object_id: str) -> ContentObject | None:
        return cast(
            ContentObject | None,
            await self.session.get(ContentObject, content_object_id),
        )

    async def get_asset(self, asset_id: str) -> ContentAsset | None:
        return cast(ContentAsset | None, await self.session.get(ContentAsset, asset_id))
