from __future__ import annotations

from typing import cast
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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

    async def get_or_create(self, owner_user_id: str) -> SnapshotUserSettings:
        statement = (
            postgresql_insert(SnapshotUserSettings)
            .values(owner_user_id=owner_user_id)
            .on_conflict_do_nothing()
            .returning(SnapshotUserSettings)
        )
        settings = cast(SnapshotUserSettings | None, await self.session.scalar(statement))
        if settings is not None:
            return settings

        existing = await self.get(owner_user_id)
        if existing is None:
            raise RuntimeError(f"Failed to load snapshot settings after conflict: {owner_user_id}")
        return existing


class SnapshotJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, job: SnapshotJob) -> None:
        self.session.add(job)

    async def add_once(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        source_asset_id: str | None,
        job_type: str,
        status: str,
        correlation_id: str | None,
        source_event_id: str | None,
    ) -> None:
        statement = postgresql_insert(SnapshotJob).values(
            id=str(uuid4()),
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            source_asset_id=source_asset_id,
            job_type=job_type,
            status=status,
            attempts=0,
            max_attempts=3,
            correlation_id=correlation_id,
            source_event_id=source_event_id,
            metadata_={},
        )
        await self.session.execute(
            statement.on_conflict_do_update(
                constraint="uq_snapshot_jobs_object_asset_type",
                set_={
                    "status": status,
                    "attempts": 0,
                    "correlation_id": correlation_id,
                    "source_event_id": source_event_id,
                    "error_message": None,
                    "last_error": None,
                    "started_at": None,
                    "finished_at": None,
                },
                where=SnapshotJob.status == "failed",
            )
        )

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

    async def get_for_asset(
        self,
        *,
        source_asset_id: str,
        job_type: str,
    ) -> SnapshotJob | None:
        query = select(SnapshotJob).where(
            SnapshotJob.source_asset_id == source_asset_id,
            SnapshotJob.job_type == job_type,
        )
        return cast(SnapshotJob | None, await self.session.scalar(query))

    async def list_pending(self, limit: int) -> list[SnapshotJob]:
        query = (
            select(SnapshotJob)
            .where(SnapshotJob.status == "pending")
            .order_by(SnapshotJob.created_at.asc())
            .limit(limit)
        )
        return list(await self.session.scalars(query))

    async def list_pending_for_object(
        self,
        *,
        content_object_id: str,
        limit: int,
    ) -> list[SnapshotJob]:
        query = (
            select(SnapshotJob)
            .where(
                SnapshotJob.content_object_id == content_object_id,
                SnapshotJob.status.in_(["pending", "retrying"]),
            )
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
            await self.session.scalar(
                select(ContentObject)
                .options(selectinload(ContentObject.assets))
                .where(ContentObject.id == content_object_id)
            ),
        )

    async def get_asset(self, asset_id: str) -> ContentAsset | None:
        return cast(ContentAsset | None, await self.session.get(ContentAsset, asset_id))
