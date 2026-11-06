"""User-facing tag operations (CRUD, manual assignment, suggestion review, merge)."""

from __future__ import annotations

from collections.abc import Collection
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.modules.content.models import ContentObject
from app.modules.content.sync import touch_content_objects
from app.modules.tags.ai import tagging_enabled
from app.modules.tags.contracts import TagAssignmentStatus
from app.modules.tags.errors import (
    TagConflictError,
    TaggingDisabledError,
    TagNotFoundError,
    TagValidationError,
)
from app.modules.tags.infrastructure.repositories import TagsRepository, index_tags_by_slug
from app.modules.tags.models import (
    ACTIVE_ASSIGNMENT_STATUSES,
    TAGGING_JOB_SUGGEST,
    ContentTagAssignment,
    Tag,
    TaggingJob,
)
from app.modules.tags.schemas import JobStatusCountResponse, TagsJobMetricsResponse
from app.modules.tags.text import slugify_label
from app.modules.taxonomy.models import ClassificationFeedback


class TagsService:
    """Request-path tag operations. Construction is cheap (no clients, no I/O)."""

    def __init__(self, session: AsyncSession, *, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.repository = TagsRepository(session)

    # --- tags ------------------------------------------------------------------------------
    async def create_tag(
        self,
        *,
        owner_user_id: str,
        name: str,
        description: str | None,
        tag_kind: str | None,
        created_by_user_id: str | None,
        aliases: list[str] | None = None,
    ) -> Tag:
        clean_name, tag_slug = _name_and_slug(name)
        normalized_aliases = _normalize_aliases(aliases or [], primary_slug=tag_slug)
        if await self.repository.find_tags_by_slugs(
            owner_user_id=owner_user_id, slugs=[tag_slug, *normalized_aliases]
        ):
            raise TagConflictError
        tag = Tag(
            owner_user_id=owner_user_id,
            name=clean_name,
            slug=tag_slug,
            description=description,
            tag_kind=tag_kind,
            aliases=normalized_aliases,
            created_by_type="user",
            created_by_user_id=created_by_user_id,
            source="manual",
            source_detail={},
            is_archived=False,
        )
        self.session.add(tag)
        await self.session.commit()
        return tag

    async def get_tag(self, *, owner_user_id: str, tag_id: str) -> Tag:
        tag = await self.repository.get_tag(owner_user_id=owner_user_id, tag_id=tag_id)
        if tag is None:
            raise TagNotFoundError
        return tag

    async def update_tag(
        self,
        *,
        owner_user_id: str,
        tag_id: str,
        name: str | None,
        description: str | None,
        tag_kind: str | None,
        aliases: list[str] | None,
        is_archived: bool | None,
    ) -> Tag:
        tag = await self.get_tag(owner_user_id=owner_user_id, tag_id=tag_id)
        new_slugs: list[str] = []
        if name is not None:
            tag.name, tag.slug = _name_and_slug(name)
            new_slugs.append(tag.slug)
        if aliases is not None:
            tag.aliases = _normalize_aliases(aliases, primary_slug=tag.slug)
            new_slugs.extend(tag.aliases)
        if new_slugs and await self.repository.find_tags_by_slugs(
            owner_user_id=owner_user_id, slugs=new_slugs, except_tag_id=tag.id
        ):
            raise TagConflictError
        if description is not None:
            tag.description = description
        if tag_kind is not None:
            tag.tag_kind = tag_kind
        if is_archived is not None:
            tag.is_archived = is_archived
        await self._touch_tagged_content(owner_user_id=owner_user_id, tag_ids=[tag.id])
        await self.session.commit()
        await self.session.refresh(tag)
        return tag

    async def archive_tag(self, *, owner_user_id: str, tag_id: str) -> None:
        tag = await self.get_tag(owner_user_id=owner_user_id, tag_id=tag_id)
        tag.is_archived = True
        await self.session.commit()

    async def list_tags(self, *, owner_user_id: str, include_archived: bool = False) -> list[Tag]:
        return await self.repository.list_tags(
            owner_user_id=owner_user_id, include_archived=include_archived
        )

    async def merge_tags(
        self,
        *,
        owner_user_id: str,
        source_tag_id: str,
        target_tag_id: str,
    ) -> Tag:
        """Move every active assignment of `source` to `target` and archive `source`."""
        if source_tag_id == target_tag_id:
            raise TagConflictError
        source = await self.get_tag(owner_user_id=owner_user_id, tag_id=source_tag_id)
        target = await self.get_tag(owner_user_id=owner_user_id, tag_id=target_tag_id)
        if target.is_archived:
            raise TagConflictError
        active = ContentTagAssignment.status.in_(ACTIVE_ASSIGNMENT_STATUSES)
        affected = list(
            await self.session.scalars(
                select(ContentTagAssignment.content_object_id).where(
                    ContentTagAssignment.owner_user_id == owner_user_id,
                    ContentTagAssignment.tag_id == source.id,
                    active,
                )
            )
        )
        if affected:
            already_on_target = list(
                await self.session.scalars(
                    select(ContentTagAssignment.content_object_id).where(
                        ContentTagAssignment.owner_user_id == owner_user_id,
                        ContentTagAssignment.tag_id == target.id,
                        ContentTagAssignment.content_object_id.in_(affected),
                        active,
                    )
                )
            )
            source_active = (
                ContentTagAssignment.owner_user_id == owner_user_id,
                ContentTagAssignment.tag_id == source.id,
                active,
            )
            await self.session.execute(
                update(ContentTagAssignment)
                .where(
                    *source_active,
                    ContentTagAssignment.content_object_id.in_(already_on_target),
                )
                .values(status=TagAssignmentStatus.REMOVED.value)
            )
            await self.session.execute(
                update(ContentTagAssignment).where(*source_active).values(tag_id=target.id)
            )
            self.session.add_all(
                ClassificationFeedback(
                    id=str(uuid4()),
                    owner_user_id=owner_user_id,
                    content_object_id=content_object_id,
                    target_type="tag",
                    target_id=target.id,
                    action="changed",
                    previous_target_id=source.id,
                    new_target_id=target.id,
                    reason="Tag merge.",
                    source="system",
                )
                for content_object_id in affected
            )
            await touch_content_objects(self.session, affected)
        source.is_archived = True
        target.aliases = _normalize_aliases(
            [*target.aliases, source.slug, *source.aliases], primary_slug=target.slug
        )
        await self.session.commit()
        await self.session.refresh(target)
        return target

    # --- assignments -----------------------------------------------------------------------
    async def assign_tag_to_content(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        tag_id: str,
        assigned_by_user_id: str | None,
        reasoning: str | None = None,
        commit: bool = True,
    ) -> tuple[ContentTagAssignment, bool]:
        """Manually assign (or accept a pending suggestion of) a tag.

        Returns the assignment and whether a new one was created.
        """
        await self._ensure_content(owner_user_id=owner_user_id, content_object_id=content_object_id)
        tag = await self.get_tag(owner_user_id=owner_user_id, tag_id=tag_id)
        if tag.is_archived:
            raise TagConflictError
        existing = await self.repository.get_active_assignment(
            owner_user_id=owner_user_id, content_object_id=content_object_id, tag_id=tag_id
        )
        created = existing is None
        if existing is None:
            assignment = ContentTagAssignment(
                owner_user_id=owner_user_id,
                content_object_id=content_object_id,
                tag=tag,
                status=TagAssignmentStatus.ACCEPTED.value,
                assigned_by_type="user",
                assigned_by_user_id=assigned_by_user_id,
                source="manual",
                source_detail={},
                reasoning=reasoning,
            )
            self.session.add(assignment)
            self._record_feedback(
                owner_user_id, content_object_id, tag.id, "manually_assigned", reasoning
            )
        else:
            assignment = existing
            if existing.status == TagAssignmentStatus.SUGGESTED.value:
                existing.status = TagAssignmentStatus.ACCEPTED.value
                existing.assigned_by_type = "user"
                existing.assigned_by_user_id = assigned_by_user_id
                existing.reasoning = reasoning or existing.reasoning
                self._record_feedback(
                    owner_user_id, content_object_id, tag.id, "accepted", reasoning
                )
        await self.session.flush()
        await touch_content_objects(self.session, [content_object_id])
        if commit:
            await self.session.commit()
        return assignment, created

    async def replace_manual_tags_for_content(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        tag_names: list[str],
        assigned_by_user_id: str | None,
    ) -> None:
        """Make the accepted tags of a content object exactly `tag_names` (by slug/alias).

        Creates missing tags. Bulk queries only; never commits.
        """
        desired: dict[str, str] = {}
        for raw_name in tag_names:
            clean = " ".join(raw_name.split())
            slug = slugify_label(clean)
            if clean and slug:
                desired.setdefault(slug, clean)
        existing = index_tags_by_slug(
            await self.repository.find_tags_by_slugs(
                owner_user_id=owner_user_id, slugs=list(desired)
            )
        )
        missing = [slug for slug in desired if slug not in existing]
        if missing:
            await self.repository.insert_missing_tags(
                [
                    {
                        "id": str(uuid4()),
                        "owner_user_id": owner_user_id,
                        "name": desired[slug][:255],
                        "slug": slug[:255],
                        "aliases": [],
                        "created_by_type": "user",
                        "created_by_user_id": assigned_by_user_id,
                        "source": "manual",
                        "source_detail": {},
                        "is_archived": False,
                    }
                    for slug in missing
                ]
            )
            existing.update(
                index_tags_by_slug(
                    await self.repository.find_tags_by_slugs(
                        owner_user_id=owner_user_id, slugs=missing
                    )
                )
            )
        desired_tags = {tag.id: tag for slug in desired if (tag := existing.get(slug))}

        active = await self.repository.list_assignments_for_content(
            owner_user_id=owner_user_id, content_object_id=content_object_id
        )
        active_by_tag = {assignment.tag_id: assignment for assignment in active}
        changed = False
        for assignment in active:
            if assignment.tag_id not in desired_tags:
                assignment.status = TagAssignmentStatus.REMOVED.value
                assignment.assigned_by_type = "user"
                assignment.assigned_by_user_id = assigned_by_user_id
                assignment.source = "manual"
                changed = True
            elif assignment.status == TagAssignmentStatus.SUGGESTED.value:
                assignment.status = TagAssignmentStatus.ACCEPTED.value
                assignment.assigned_by_type = "user"
                assignment.assigned_by_user_id = assigned_by_user_id
                changed = True
        for tag_id, tag in desired_tags.items():
            if tag_id in active_by_tag:
                continue
            if tag.is_archived:
                tag.is_archived = False
            self.session.add(
                ContentTagAssignment(
                    owner_user_id=owner_user_id,
                    content_object_id=content_object_id,
                    tag_id=tag_id,
                    status=TagAssignmentStatus.ACCEPTED.value,
                    assigned_by_type="user",
                    assigned_by_user_id=assigned_by_user_id,
                    source="manual",
                    source_detail={},
                    reasoning="Assigned from content tag_names.",
                )
            )
            changed = True
        if changed:
            await self.session.flush()
            await touch_content_objects(self.session, [content_object_id])

    async def remove_tag_from_content(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        tag_id: str,
        assigned_by_user_id: str | None,
    ) -> None:
        assignment = await self.repository.get_active_assignment(
            owner_user_id=owner_user_id, content_object_id=content_object_id, tag_id=tag_id
        )
        if assignment is None:
            raise TagNotFoundError
        assignment.status = TagAssignmentStatus.REMOVED.value
        assignment.assigned_by_type = "user"
        assignment.assigned_by_user_id = assigned_by_user_id
        assignment.source = "manual"
        self._record_feedback(owner_user_id, content_object_id, tag_id, "removed", None)
        await touch_content_objects(self.session, [content_object_id])
        await self.session.commit()

    async def list_tags_for_content(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        statuses: Collection[str],
    ) -> list[ContentTagAssignment]:
        await self._ensure_content(owner_user_id=owner_user_id, content_object_id=content_object_id)
        return await self.repository.list_assignments_for_content(
            owner_user_id=owner_user_id, content_object_id=content_object_id, statuses=statuses
        )

    async def list_active_tags_for_contents(
        self,
        *,
        owner_user_id: str,
        content_object_ids: list[str],
    ) -> dict[str, list[Tag]]:
        """Accepted tags per content object (one query), ordered by tag name."""
        assignments = await self.repository.list_assignments_for_contents(
            owner_user_id=owner_user_id,
            content_object_ids=content_object_ids,
            statuses=(TagAssignmentStatus.ACCEPTED.value,),
        )
        result: dict[str, list[Tag]] = {content_id: [] for content_id in content_object_ids}
        for assignment in assignments:
            result.setdefault(assignment.content_object_id, []).append(assignment.tag)
        return result

    async def list_review_suggestions(
        self, *, owner_user_id: str, limit: int = 50, offset: int = 0
    ) -> list[ContentTagAssignment]:
        return await self.repository.list_review_suggestions(
            owner_user_id=owner_user_id, limit=limit, offset=offset
        )

    async def accept_suggestion(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        assignment_id: str,
        assigned_by_user_id: str,
    ) -> ContentTagAssignment:
        return await self._review_suggestion(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            assignment_id=assignment_id,
            assigned_by_user_id=assigned_by_user_id,
            status=TagAssignmentStatus.ACCEPTED,
        )

    async def reject_suggestion(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        assignment_id: str,
        assigned_by_user_id: str,
    ) -> ContentTagAssignment:
        return await self._review_suggestion(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            assignment_id=assignment_id,
            assigned_by_user_id=assigned_by_user_id,
            status=TagAssignmentStatus.REJECTED,
        )

    # --- jobs ------------------------------------------------------------------------------
    async def enqueue_content_tag_suggestions(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        priority: int = 200,
    ) -> TaggingJob:
        """User-requested (re)tagging. Commits."""
        if not tagging_enabled(self.settings):
            raise TaggingDisabledError
        await self._ensure_content(owner_user_id=owner_user_id, content_object_id=content_object_id)
        job_id = await self.repository.enqueue_job(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            job_type=TAGGING_JOB_SUGGEST,
            priority=priority,
            max_attempts=self.settings.worker_max_job_attempts,
        )
        await self.session.commit()
        job = await self.repository.get_job(job_id)
        if job is None:  # pragma: no cover - deleted concurrently with its content object
            raise TagNotFoundError
        return job

    async def list_jobs_for_content(
        self, *, owner_user_id: str, content_object_id: str
    ) -> list[TaggingJob]:
        await self._ensure_content(owner_user_id=owner_user_id, content_object_id=content_object_id)
        return await self.repository.list_jobs_for_content(
            owner_user_id=owner_user_id, content_object_id=content_object_id
        )

    async def job_metrics(self, *, owner_user_id: str) -> TagsJobMetricsResponse:
        rows = await self.repository.count_jobs_by_status(owner_user_id=owner_user_id)
        return TagsJobMetricsResponse(
            jobs_by_status=[
                JobStatusCountResponse(status=status, count=count) for status, count in rows
            ],
            suggestions_pending=await self.repository.count_suggestions(
                owner_user_id=owner_user_id
            ),
        )

    # --- helpers ---------------------------------------------------------------------------
    async def _review_suggestion(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        assignment_id: str,
        assigned_by_user_id: str,
        status: TagAssignmentStatus,
    ) -> ContentTagAssignment:
        assignment = await self.repository.get_assignment(
            owner_user_id=owner_user_id, assignment_id=assignment_id
        )
        if assignment is None or assignment.content_object_id != content_object_id:
            raise TagNotFoundError
        if assignment.status != TagAssignmentStatus.SUGGESTED.value:
            raise TagConflictError
        assignment.status = status.value
        assignment.assigned_by_type = "user"
        assignment.assigned_by_user_id = assigned_by_user_id
        self._record_feedback(
            owner_user_id, content_object_id, assignment.tag_id, status.value, assignment.reasoning
        )
        await touch_content_objects(self.session, [content_object_id])
        await self.session.commit()
        return assignment

    async def _ensure_content(self, *, owner_user_id: str, content_object_id: str) -> None:
        exists = await self.session.scalar(
            select(ContentObject.id).where(
                ContentObject.owner_user_id == owner_user_id,
                ContentObject.id == content_object_id,
            )
        )
        if exists is None:
            raise TagNotFoundError

    async def _touch_tagged_content(self, *, owner_user_id: str, tag_ids: list[str]) -> None:
        """A renamed/archived tag changes how every note carrying it renders."""
        content_ids = list(
            await self.session.scalars(
                select(ContentTagAssignment.content_object_id).where(
                    ContentTagAssignment.owner_user_id == owner_user_id,
                    ContentTagAssignment.tag_id.in_(tag_ids),
                    ContentTagAssignment.status.in_(ACTIVE_ASSIGNMENT_STATUSES),
                )
            )
        )
        if content_ids:
            await touch_content_objects(self.session, content_ids)

    def _record_feedback(
        self,
        owner_user_id: str,
        content_object_id: str,
        tag_id: str | None,
        action: str,
        reason: str | None,
    ) -> None:
        self.session.add(
            ClassificationFeedback(
                owner_user_id=owner_user_id,
                content_object_id=content_object_id,
                target_type="tag",
                target_id=tag_id,
                action=action,
                reason=reason,
                source="user",
            )
        )


def _name_and_slug(name: str) -> tuple[str, str]:
    clean = " ".join(name.split())
    if not clean:
        raise TagValidationError("Tag name must not be empty.")
    slug = slugify_label(clean)
    if not slug:
        raise TagValidationError("Tag name must contain letters or digits.")
    return clean[:255], slug[:255]


def _normalize_aliases(aliases: list[str], *, primary_slug: str) -> list[str]:
    slugs = (slugify_label(alias) for alias in aliases)
    return list(dict.fromkeys(slug for slug in slugs if slug and slug != primary_slug))
