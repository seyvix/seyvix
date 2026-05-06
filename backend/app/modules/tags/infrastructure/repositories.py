from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.content.models import ContentObject
from app.modules.tags.models import ContentTagAssignment, Tag, TaggingJob


class TagsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add_tag(self, tag: Tag) -> None:
        self.session.add(tag)

    def add_assignment(self, assignment: ContentTagAssignment) -> None:
        self.session.add(assignment)

    def add_job(self, job: TaggingJob) -> None:
        self.session.add(job)

    async def get_tag(self, *, owner_user_id: str, tag_id: str) -> Tag | None:
        query = select(Tag).where(Tag.owner_user_id == owner_user_id, Tag.id == tag_id)
        return cast(Tag | None, await self.session.scalar(query))

    async def get_tag_by_slug(self, *, owner_user_id: str, slug: str) -> Tag | None:
        query = select(Tag).where(Tag.owner_user_id == owner_user_id, Tag.slug == slug)
        return cast(Tag | None, await self.session.scalar(query))

    async def get_tag_by_slug_or_alias(self, *, owner_user_id: str, slug: str) -> Tag | None:
        direct = await self.get_tag_by_slug(owner_user_id=owner_user_id, slug=slug)
        if direct is not None:
            return direct
        tags = await self.list_tags(owner_user_id=owner_user_id, include_archived=True)
        return next((tag for tag in tags if slug in set(tag.aliases)), None)

    async def list_tags(self, *, owner_user_id: str, include_archived: bool) -> list[Tag]:
        query = select(Tag).where(Tag.owner_user_id == owner_user_id)
        if not include_archived:
            query = query.where(Tag.is_archived.is_(False))
        query = query.order_by(Tag.name.asc())
        return list(await self.session.scalars(query))

    async def list_active_assignments_for_content(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        statuses: set[str] | None = None,
    ) -> list[ContentTagAssignment]:
        active_statuses = statuses or {"suggested", "accepted"}
        query = (
            select(ContentTagAssignment)
            .options(selectinload(ContentTagAssignment.tag))
            .where(
                ContentTagAssignment.owner_user_id == owner_user_id,
                ContentTagAssignment.content_object_id == content_object_id,
                ContentTagAssignment.status.in_(active_statuses),
            )
            .order_by(Tag.name.asc())
            .join(Tag, ContentTagAssignment.tag_id == Tag.id)
        )
        return list(await self.session.scalars(query))

    async def list_active_assignments_for_contents(
        self,
        *,
        owner_user_id: str,
        content_object_ids: list[str],
        statuses: set[str] | None = None,
    ) -> list[ContentTagAssignment]:
        if not content_object_ids:
            return []
        active_statuses = statuses or {"accepted"}
        query = (
            select(ContentTagAssignment)
            .options(selectinload(ContentTagAssignment.tag))
            .where(
                ContentTagAssignment.owner_user_id == owner_user_id,
                ContentTagAssignment.content_object_id.in_(content_object_ids),
                ContentTagAssignment.status.in_(active_statuses),
            )
            .join(Tag, ContentTagAssignment.tag_id == Tag.id)
            .order_by(Tag.name.asc())
        )
        return list(await self.session.scalars(query))

    async def list_review_suggestions(
        self,
        *,
        owner_user_id: str,
        limit: int,
        offset: int,
    ) -> list[ContentTagAssignment]:
        query = (
            select(ContentTagAssignment)
            .options(selectinload(ContentTagAssignment.tag))
            .where(
                ContentTagAssignment.owner_user_id == owner_user_id,
                ContentTagAssignment.status == "suggested",
            )
            .order_by(ContentTagAssignment.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(await self.session.scalars(query))

    async def get_assignment(
        self,
        *,
        owner_user_id: str,
        assignment_id: str,
    ) -> ContentTagAssignment | None:
        query = (
            select(ContentTagAssignment)
            .options(selectinload(ContentTagAssignment.tag))
            .where(
                ContentTagAssignment.owner_user_id == owner_user_id,
                ContentTagAssignment.id == assignment_id,
            )
        )
        return cast(ContentTagAssignment | None, await self.session.scalar(query))

    async def get_active_assignment(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        tag_id: str,
    ) -> ContentTagAssignment | None:
        query = (
            select(ContentTagAssignment)
            .options(selectinload(ContentTagAssignment.tag))
            .where(
                ContentTagAssignment.owner_user_id == owner_user_id,
                ContentTagAssignment.content_object_id == content_object_id,
                ContentTagAssignment.tag_id == tag_id,
                ContentTagAssignment.status.in_(("suggested", "accepted")),
            )
        )
        return cast(ContentTagAssignment | None, await self.session.scalar(query))

    async def enqueue_job(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        job_type: str,
        priority: int,
        source_event_id: str | None = None,
        correlation_id: str | None = None,
        content_updated_at_snapshot: datetime | None = None,
    ) -> TaggingJob:
        if source_event_id is not None:
            existing_by_event = cast(
                TaggingJob | None,
                await self.session.scalar(
                    select(TaggingJob).where(TaggingJob.source_event_id == source_event_id)
                ),
            )
            if existing_by_event is not None:
                return existing_by_event

        if content_updated_at_snapshot is None:
            content_updated_at_snapshot = await self.session.scalar(
                select(ContentObject.updated_at).where(
                    ContentObject.owner_user_id == owner_user_id,
                    ContentObject.id == content_object_id,
                )
            )

        existing_query = select(TaggingJob).where(
            TaggingJob.owner_user_id == owner_user_id,
            TaggingJob.content_object_id == content_object_id,
            TaggingJob.job_type == job_type,
            TaggingJob.status.in_(("pending", "processing")),
        )
        existing = cast(TaggingJob | None, await self.session.scalar(existing_query))
        if existing is not None:
            if priority > existing.priority:
                existing.priority = priority
            if source_event_id is not None:
                existing.source_event_id = source_event_id
            if correlation_id is not None:
                existing.correlation_id = correlation_id
            if content_updated_at_snapshot is not None:
                existing.content_updated_at_snapshot = content_updated_at_snapshot
            existing.last_error = None
            existing.run_after = datetime.now(UTC)
            if existing.status == "processing":
                existing.status = "pending"
                existing.locked_at = None
                existing.locked_by = None
                existing.attempts = 0
            await self.session.flush()
            return existing

        job = TaggingJob(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            job_type=job_type,
            status="pending",
            priority=priority,
            source_event_id=source_event_id,
            correlation_id=correlation_id,
            content_updated_at_snapshot=content_updated_at_snapshot,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def list_jobs_for_content(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
    ) -> list[TaggingJob]:
        query = (
            select(TaggingJob)
            .where(
                TaggingJob.owner_user_id == owner_user_id,
                TaggingJob.content_object_id == content_object_id,
            )
            .order_by(TaggingJob.created_at.desc())
        )
        return list(await self.session.scalars(query))

    async def claim_pending_jobs(
        self,
        *,
        limit: int,
        worker_id: str,
        lock_timeout_seconds: int,
    ) -> list[TaggingJob]:
        now = datetime.now(UTC)
        stale_before = now - timedelta(seconds=lock_timeout_seconds)
        query = (
            select(TaggingJob)
            .where(
                ((TaggingJob.status == "pending") & (TaggingJob.run_after <= now))
                | ((TaggingJob.status == "processing") & (TaggingJob.locked_at < stale_before))
            )
            .order_by(TaggingJob.priority.desc(), TaggingJob.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        jobs = list(await self.session.scalars(query))
        for job in jobs:
            job.status = "processing"
            job.attempts += 1
            job.locked_at = now
            job.locked_by = worker_id
        await self.session.flush()
        return jobs
