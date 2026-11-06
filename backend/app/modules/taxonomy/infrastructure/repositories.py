from __future__ import annotations

from typing import cast

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.content.models import ContentObject
from app.modules.tags.infrastructure.repositories import upsert_content_job
from app.modules.taxonomy.models import (
    CLASSIFY_CONTENT_JOB,
    INBOX_PATH,
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

    async def list_categories_by_paths(
        self, *, owner_user_id: str, paths: list[str]
    ) -> list[TaxonomyCategory]:
        if not paths:
            return []
        query = select(TaxonomyCategory).where(
            TaxonomyCategory.owner_user_id == owner_user_id,
            TaxonomyCategory.path.in_(paths),
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

    async def content_exists(self, *, owner_user_id: str, content_object_id: str) -> bool:
        query = select(ContentObject.id).where(
            ContentObject.owner_user_id == owner_user_id,
            ContentObject.id == content_object_id,
        )
        return await self.session.scalar(query) is not None

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

    async def list_current_assignments_in_paths(
        self, *, owner_user_id: str, paths: list[str]
    ) -> list[TaxonomyContentAssignment]:
        if not paths:
            return []
        query = select(TaxonomyContentAssignment).where(
            TaxonomyContentAssignment.owner_user_id == owner_user_id,
            TaxonomyContentAssignment.is_current.is_(True),
            TaxonomyContentAssignment.category_path_snapshot.in_(paths),
        )
        return list(await self.session.scalars(query))

    async def list_children(self, *, owner_user_id: str, parent_id: str) -> list[TaxonomyCategory]:
        query = (
            select(TaxonomyCategory)
            .where(
                TaxonomyCategory.owner_user_id == owner_user_id,
                TaxonomyCategory.parent_id == parent_id,
                TaxonomyCategory.is_archived.is_(False),
            )
            .order_by(TaxonomyCategory.sort_order.asc(), TaxonomyCategory.name.asc())
        )
        return list(await self.session.scalars(query))

    async def list_subtree(
        self, *, owner_user_id: str, path: str, include_archived: bool
    ) -> list[TaxonomyCategory]:
        escaped = path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = select(TaxonomyCategory).where(
            TaxonomyCategory.owner_user_id == owner_user_id,
            (TaxonomyCategory.path == path)
            | TaxonomyCategory.path.like(f"{escaped}/%", escape="\\"),
        )
        if not include_archived:
            query = query.where(TaxonomyCategory.is_archived.is_(False))
        return list(await self.session.scalars(query))

    async def inbox_content_ids(self, *, owner_user_id: str) -> list[str]:
        query = select(TaxonomyContentAssignment.content_object_id).where(
            TaxonomyContentAssignment.owner_user_id == owner_user_id,
            TaxonomyContentAssignment.is_current.is_(True),
            TaxonomyContentAssignment.category_path_snapshot == INBOX_PATH,
        )
        return list(await self.session.scalars(query))

    # --- classification jobs -------------------------------------------------------------
    async def enqueue_job(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        priority: int,
        max_attempts: int,
        source_event_id: str | None = None,
        correlation_id: str | None = None,
    ) -> str:
        return await upsert_content_job(
            self.session,
            TaxonomyClassificationJob,
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            job_type=CLASSIFY_CONTENT_JOB,
            priority=priority,
            max_attempts=max_attempts,
            source_event_id=source_event_id,
            correlation_id=correlation_id,
        )

    async def get_job(
        self, job_id: str, *, for_update: bool = False
    ) -> TaxonomyClassificationJob | None:
        query = select(TaxonomyClassificationJob).where(TaxonomyClassificationJob.id == job_id)
        if for_update:
            query = query.with_for_update()
        return cast(TaxonomyClassificationJob | None, await self.session.scalar(query))

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

    async def count_jobs_by_status(self, *, owner_user_id: str) -> list[tuple[str, int]]:
        rows = await self.session.execute(
            select(TaxonomyClassificationJob.status, func.count(TaxonomyClassificationJob.id))
            .where(TaxonomyClassificationJob.owner_user_id == owner_user_id)
            .group_by(TaxonomyClassificationJob.status)
        )
        return [(str(status), int(count)) for status, count in rows.all()]

    async def count_pending_proposals(self, *, owner_user_id: str) -> int:
        count = await self.session.scalar(
            select(func.count(TaxonomyContentAssignment.id)).where(
                TaxonomyContentAssignment.owner_user_id == owner_user_id,
                TaxonomyContentAssignment.status == "proposed",
                TaxonomyContentAssignment.is_current.is_(True),
            )
        )
        return int(count or 0)

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
