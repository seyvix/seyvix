from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

from app.modules.tags.models import ContentTagAssignment, Tag, TaggingJob
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


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
    ) -> TaggingJob:
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
                await self.session.flush()
            return existing

        job = TaggingJob(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            job_type=job_type,
            status="pending",
            priority=priority,
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
