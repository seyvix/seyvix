from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.content.models import ContentObject
from app.modules.taxonomy.models import (
    ClassificationFeedback,
    TaxonomyCategory,
    TaxonomyCategoryProfile,
    TaxonomyClassificationJob,
    TaxonomyContentAssignment,
    TaxonomyUserSettings,
)


class TaxonomyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add_category(self, category: TaxonomyCategory) -> None:
        self.session.add(category)

    def add_profile(self, profile: TaxonomyCategoryProfile) -> None:
        self.session.add(profile)

    def add_settings(self, settings: TaxonomyUserSettings) -> None:
        self.session.add(settings)

    def add_assignment(self, assignment: TaxonomyContentAssignment) -> None:
        self.session.add(assignment)

    def add_feedback(self, feedback: ClassificationFeedback) -> None:
        self.session.add(feedback)

    def add_classification_job(self, job: TaxonomyClassificationJob) -> None:
        self.session.add(job)

    async def get_category(
        self,
        *,
        owner_user_id: str,
        category_id: str,
        include_archived: bool = True,
    ) -> TaxonomyCategory | None:
        query = select(TaxonomyCategory).where(
            TaxonomyCategory.owner_user_id == owner_user_id,
            TaxonomyCategory.id == category_id,
        )
        if not include_archived:
            query = query.where(TaxonomyCategory.is_archived.is_(False))
        return cast(TaxonomyCategory | None, await self.session.scalar(query))

    async def get_category_by_path(
        self,
        *,
        owner_user_id: str,
        path: str,
        include_archived: bool = True,
    ) -> TaxonomyCategory | None:
        query = select(TaxonomyCategory).where(
            TaxonomyCategory.owner_user_id == owner_user_id,
            TaxonomyCategory.path == path,
        )
        if not include_archived:
            query = query.where(TaxonomyCategory.is_archived.is_(False))
        return cast(TaxonomyCategory | None, await self.session.scalar(query))

    async def list_categories(
        self,
        *,
        owner_user_id: str,
        include_archived: bool,
    ) -> list[TaxonomyCategory]:
        query = select(TaxonomyCategory).where(TaxonomyCategory.owner_user_id == owner_user_id)
        if not include_archived:
            query = query.where(TaxonomyCategory.is_archived.is_(False))
        query = query.order_by(
            TaxonomyCategory.depth.asc(),
            TaxonomyCategory.sort_order.asc(),
            TaxonomyCategory.name.asc(),
        )
        return list(await self.session.scalars(query))

    async def list_categories_with_profiles(
        self,
        *,
        owner_user_id: str,
        include_archived: bool,
    ) -> list[TaxonomyCategory]:
        query = (
            select(TaxonomyCategory)
            .options(selectinload(TaxonomyCategory.profile))
            .where(TaxonomyCategory.owner_user_id == owner_user_id)
        )
        if not include_archived:
            query = query.where(TaxonomyCategory.is_archived.is_(False))
        query = query.order_by(
            TaxonomyCategory.depth.desc(),
            TaxonomyCategory.sort_order.asc(),
            TaxonomyCategory.name.asc(),
        )
        return list(await self.session.scalars(query))

    async def search_categories(
        self,
        *,
        owner_user_id: str,
        query_text: str,
        include_archived: bool,
    ) -> list[TaxonomyCategory]:
        needle = f"%{query_text.casefold()}%"
        query = (
            select(TaxonomyCategory)
            .where(
                TaxonomyCategory.owner_user_id == owner_user_id,
                (
                    TaxonomyCategory.name.ilike(needle)
                    | TaxonomyCategory.slug.ilike(needle)
                    | TaxonomyCategory.path.ilike(needle)
                    | TaxonomyCategory.description.ilike(needle)
                ),
            )
            .order_by(
                TaxonomyCategory.depth.asc(),
                TaxonomyCategory.sort_order.asc(),
                TaxonomyCategory.name.asc(),
            )
        )
        if not include_archived:
            query = query.where(TaxonomyCategory.is_archived.is_(False))
        return list(await self.session.scalars(query))

    async def category_path_exists(
        self,
        *,
        owner_user_id: str,
        path: str,
        except_category_id: str | None = None,
    ) -> bool:
        query = select(TaxonomyCategory.id).where(
            TaxonomyCategory.owner_user_id == owner_user_id,
            TaxonomyCategory.path == path,
        )
        if except_category_id is not None:
            query = query.where(TaxonomyCategory.id != except_category_id)
        return await self.session.scalar(query) is not None

    async def category_slug_exists(
        self,
        *,
        owner_user_id: str,
        parent_id: str | None,
        slug: str,
        except_category_id: str | None = None,
    ) -> bool:
        query = select(TaxonomyCategory.id).where(
            TaxonomyCategory.owner_user_id == owner_user_id,
            TaxonomyCategory.slug == slug,
        )
        if parent_id is None:
            query = query.where(TaxonomyCategory.parent_id.is_(None))
        else:
            query = query.where(TaxonomyCategory.parent_id == parent_id)
        if except_category_id is not None:
            query = query.where(TaxonomyCategory.id != except_category_id)
        return await self.session.scalar(query) is not None

    async def has_children(
        self,
        *,
        owner_user_id: str,
        category_id: str,
        active_only: bool,
    ) -> bool:
        query = select(TaxonomyCategory.id).where(
            TaxonomyCategory.owner_user_id == owner_user_id,
            TaxonomyCategory.parent_id == category_id,
        )
        if active_only:
            query = query.where(TaxonomyCategory.is_archived.is_(False))
        return await self.session.scalar(query) is not None

    async def has_categories(self, *, owner_user_id: str) -> bool:
        query = select(TaxonomyCategory.id).where(TaxonomyCategory.owner_user_id == owner_user_id)
        return await self.session.scalar(query) is not None

    async def get_profile(
        self,
        *,
        category_id: str,
    ) -> TaxonomyCategoryProfile | None:
        query = select(TaxonomyCategoryProfile).where(
            TaxonomyCategoryProfile.category_id == category_id
        )
        return cast(TaxonomyCategoryProfile | None, await self.session.scalar(query))

    async def get_settings(self, *, owner_user_id: str) -> TaxonomyUserSettings | None:
        query = select(TaxonomyUserSettings).where(
            TaxonomyUserSettings.owner_user_id == owner_user_id
        )
        return cast(TaxonomyUserSettings | None, await self.session.scalar(query))

    async def get_content_object(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
    ) -> ContentObject | None:
        query = select(ContentObject).where(
            ContentObject.owner_user_id == owner_user_id,
            ContentObject.id == content_object_id,
        )
        return cast(ContentObject | None, await self.session.scalar(query))

    async def list_assignments(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
    ) -> list[TaxonomyContentAssignment]:
        query = (
            select(TaxonomyContentAssignment)
            .where(
                TaxonomyContentAssignment.owner_user_id == owner_user_id,
                TaxonomyContentAssignment.content_object_id == content_object_id,
            )
            .order_by(TaxonomyContentAssignment.created_at.desc())
        )
        return list(await self.session.scalars(query))

    async def list_review_assignments(
        self,
        *,
        owner_user_id: str,
        limit: int,
        offset: int,
    ) -> list[TaxonomyContentAssignment]:
        query = (
            select(TaxonomyContentAssignment)
            .where(
                TaxonomyContentAssignment.owner_user_id == owner_user_id,
                TaxonomyContentAssignment.status == "proposed",
                TaxonomyContentAssignment.is_current.is_(True),
            )
            .order_by(TaxonomyContentAssignment.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(await self.session.scalars(query))

    async def get_assignment(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        assignment_id: str,
    ) -> TaxonomyContentAssignment | None:
        query = select(TaxonomyContentAssignment).where(
            TaxonomyContentAssignment.owner_user_id == owner_user_id,
            TaxonomyContentAssignment.content_object_id == content_object_id,
            TaxonomyContentAssignment.id == assignment_id,
        )
        return cast(TaxonomyContentAssignment | None, await self.session.scalar(query))

    async def get_current_assignment(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
    ) -> TaxonomyContentAssignment | None:
        query = select(TaxonomyContentAssignment).where(
            TaxonomyContentAssignment.owner_user_id == owner_user_id,
            TaxonomyContentAssignment.content_object_id == content_object_id,
            TaxonomyContentAssignment.is_current.is_(True),
        )
        return cast(TaxonomyContentAssignment | None, await self.session.scalar(query))

    async def list_current_assignments(
        self,
        *,
        owner_user_id: str,
    ) -> list[TaxonomyContentAssignment]:
        query = select(TaxonomyContentAssignment).where(
            TaxonomyContentAssignment.owner_user_id == owner_user_id,
            TaxonomyContentAssignment.is_current.is_(True),
        )
        return list(await self.session.scalars(query))

    async def enqueue_classification_job(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        job_type: str,
        priority: int,
        source_event_id: str | None,
        correlation_id: str | None,
        content_updated_at_snapshot: datetime | None = None,
    ) -> TaxonomyClassificationJob:
        if source_event_id is not None:
            existing = await self.session.scalar(
                select(TaxonomyClassificationJob).where(
                    TaxonomyClassificationJob.source_event_id == source_event_id
                )
            )
            if existing is not None:
                return existing
        if content_updated_at_snapshot is None:
            content_updated_at_snapshot = await self.session.scalar(
                select(ContentObject.updated_at).where(
                    ContentObject.owner_user_id == owner_user_id,
                    ContentObject.id == content_object_id,
                )
            )
        existing = cast(
            TaxonomyClassificationJob | None,
            await self.session.scalar(
                select(TaxonomyClassificationJob).where(
                    TaxonomyClassificationJob.owner_user_id == owner_user_id,
                    TaxonomyClassificationJob.content_object_id == content_object_id,
                    TaxonomyClassificationJob.job_type == job_type,
                    TaxonomyClassificationJob.status.in_(("pending", "processing")),
                )
            ),
        )
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
        job = TaxonomyClassificationJob(
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

    async def list_classification_jobs_for_content(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
    ) -> list[TaxonomyClassificationJob]:
        query = (
            select(TaxonomyClassificationJob)
            .where(
                TaxonomyClassificationJob.owner_user_id == owner_user_id,
                TaxonomyClassificationJob.content_object_id == content_object_id,
            )
            .order_by(TaxonomyClassificationJob.created_at.desc())
        )
        return list(await self.session.scalars(query))

    async def claim_pending_classification_jobs(
        self,
        *,
        limit: int,
        worker_id: str,
        lock_timeout_seconds: int,
    ) -> list[TaxonomyClassificationJob]:
        now = datetime.now(UTC)
        stale_before = now - timedelta(seconds=lock_timeout_seconds)
        query = (
            select(TaxonomyClassificationJob)
            .where(
                (
                    (TaxonomyClassificationJob.status == "pending")
                    & (TaxonomyClassificationJob.run_after <= now)
                )
                | (
                    (TaxonomyClassificationJob.status == "processing")
                    & (TaxonomyClassificationJob.locked_at < stale_before)
                )
            )
            .order_by(
                TaxonomyClassificationJob.priority.desc(),
                TaxonomyClassificationJob.created_at.asc(),
            )
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

    async def override_current_assignments(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        except_assignment_id: str | None = None,
    ) -> None:
        statement = (
            update(TaxonomyContentAssignment)
            .where(
                TaxonomyContentAssignment.owner_user_id == owner_user_id,
                TaxonomyContentAssignment.content_object_id == content_object_id,
                TaxonomyContentAssignment.is_current.is_(True),
            )
            .values(is_current=False, status="overridden")
        )
        if except_assignment_id is not None:
            statement = statement.where(TaxonomyContentAssignment.id != except_assignment_id)
        await self.session.execute(statement)
