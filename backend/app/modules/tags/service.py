from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import Settings, get_settings
from app.modules.content.infrastructure.repositories import ContentRepository
from app.modules.content.models import ContentObject
from app.modules.content.storage import slugify
from app.modules.llm.contracts import StructuredLLMGenerator, build_structured_llm_generator
from app.modules.snapshots.service import SnapshotService
from app.modules.tags.contracts import (
    ContentTagSuggestion,
    TagAssignmentStatus,
    TaggingJobStatusValue,
)
from app.modules.tags.infrastructure.llm_tagger import LLMContentTagger
from app.modules.tags.infrastructure.repositories import TagsRepository
from app.modules.tags.models import ContentTagAssignment, Tag, TaggingJob
from app.modules.tags.schemas import JobStatusCountResponse, TagsJobMetricsResponse
from app.modules.taxonomy.contracts import AutomaticApplyMode
from app.modules.taxonomy.models import ClassificationFeedback, TaxonomyUserSettings
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


class TagNotFoundError(Exception):
    pass


class TagConflictError(Exception):
    pass


class TagValidationError(Exception):
    pass


class TagLLMDisabledError(Exception):
    pass


@dataclass(slots=True)
class TaggingInput:
    content_object: ContentObject
    active_tags: list[Tag]
    existing_tag_candidates: list[Tag]
    excerpt: str | None


class TagsService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings | None = None,
        llm_generator: StructuredLLMGenerator | None = None,
        storage_root: Path | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.repository = TagsRepository(session)
        self.content = ContentRepository(session)
        self.snapshots = SnapshotService(
            session,
            storage_root or Path(self.settings.content_storage_root),
        )
        self.llm_generator = llm_generator or build_structured_llm_generator(
            provider_name=self.settings.tags_llm_provider or self.settings.llm_structured_provider,
            base_url=(
                self.settings.tags_llm_base_url
                if self.settings.tags_llm_base_url is not None
                else self.settings.llm_structured_base_url
            ),
            api_key=(
                self.settings.tags_llm_api_key
                if self.settings.tags_llm_api_key is not None
                else self.settings.llm_structured_api_key
            ),
            timeout_seconds=self.settings.tags_llm_timeout_seconds
            or self.settings.llm_structured_timeout_seconds,
        )

    async def create_tag(
        self,
        *,
        owner_user_id: str,
        name: str,
        description: str | None,
        tag_kind: str | None,
        created_by_user_id: str | None,
        aliases: list[str] | None = None,
        created_by_type: str = "user",
        source: str = "manual",
        source_detail: dict[str, object] | None = None,
        confidence: float | None = None,
        commit: bool = True,
    ) -> Tag:
        clean_name = self._validate_name(name)
        tag_slug = slugify(clean_name)
        if not tag_slug:
            raise TagValidationError("Tag name must produce a non-empty slug.")
        normalized_aliases = self._normalize_aliases(aliases or [], primary_name=clean_name)
        existing = await self.repository.get_tag_by_slug_or_alias(
            owner_user_id=owner_user_id,
            slug=tag_slug,
        )
        if existing is not None:
            raise TagConflictError
        await self._ensure_aliases_available(
            owner_user_id=owner_user_id,
            aliases=normalized_aliases,
        )
        tag = Tag(
            owner_user_id=owner_user_id,
            name=clean_name,
            slug=tag_slug,
            description=description,
            tag_kind=tag_kind,
            aliases=normalized_aliases,
            created_by_type=created_by_type,
            created_by_user_id=created_by_user_id,
            source=source,
            source_detail=source_detail or {},
            confidence=confidence,
            is_archived=False,
        )
        self.repository.add_tag(tag)
        await self.session.flush()
        if commit:
            await self.session.commit()
            await self.session.refresh(tag)
        return tag

    async def get_or_create_tag(
        self,
        *,
        owner_user_id: str,
        name: str,
        created_by_user_id: str | None,
        created_by_type: str,
        source: str,
        source_detail: dict[str, object] | None = None,
        confidence: float | None = None,
    ) -> Tag:
        clean_name = self._validate_name(name)
        tag_slug = slugify(clean_name)
        existing = await self.repository.get_tag_by_slug_or_alias(
            owner_user_id=owner_user_id,
            slug=tag_slug,
        )
        if existing is not None:
            return existing
        return await self.create_tag(
            owner_user_id=owner_user_id,
            name=clean_name,
            description=None,
            tag_kind=None,
            created_by_user_id=created_by_user_id,
            created_by_type=created_by_type,
            source=source,
            source_detail=source_detail,
            confidence=confidence,
            commit=False,
        )

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
        tag = await self._get_tag(owner_user_id=owner_user_id, tag_id=tag_id)
        if name is not None:
            clean_name = self._validate_name(name)
            tag_slug = slugify(clean_name)
            existing = await self.repository.get_tag_by_slug(
                owner_user_id=owner_user_id,
                slug=tag_slug,
            )
            if existing is not None and existing.id != tag.id:
                raise TagConflictError
            tag.name = clean_name
            tag.slug = tag_slug
        if description is not None:
            tag.description = description
        if tag_kind is not None:
            tag.tag_kind = tag_kind
        if aliases is not None:
            normalized_aliases = self._normalize_aliases(aliases, primary_name=tag.name)
            await self._ensure_aliases_available(
                owner_user_id=owner_user_id,
                aliases=normalized_aliases,
                except_tag_id=tag.id,
            )
            tag.aliases = normalized_aliases
        if is_archived is not None:
            tag.is_archived = is_archived
        await self.session.commit()
        await self.session.refresh(tag)
        return tag

    async def archive_tag(self, *, owner_user_id: str, tag_id: str) -> None:
        tag = await self._get_tag(owner_user_id=owner_user_id, tag_id=tag_id)
        tag.is_archived = True
        await self.session.commit()

    async def list_tags(self, *, owner_user_id: str, include_archived: bool = False) -> list[Tag]:
        return await self.repository.list_tags(
            owner_user_id=owner_user_id,
            include_archived=include_archived,
        )

    async def assign_tag_to_content(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        tag_id: str,
        assigned_by_user_id: str | None,
        reasoning: str | None = None,
        status: str = "accepted",
        assigned_by_type: str = "user",
        source: str = "manual",
        source_detail: dict[str, object] | None = None,
        confidence: float | None = None,
        commit: bool = True,
    ) -> ContentTagAssignment:
        await self._get_content_object(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
        )
        tag = await self._get_tag(owner_user_id=owner_user_id, tag_id=tag_id)
        if tag.is_archived:
            raise TagConflictError
        existing = await self.repository.get_active_assignment(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            tag_id=tag_id,
        )
        if existing is not None:
            if existing.status == "suggested" and status == "accepted":
                existing.status = TagAssignmentStatus.ACCEPTED.value
                existing.assigned_by_user_id = assigned_by_user_id
                existing.reasoning = reasoning or existing.reasoning
                if assigned_by_type == "user":
                    self._record_feedback(
                        owner_user_id=owner_user_id,
                        content_object_id=content_object_id,
                        target_id=tag_id,
                        action="accepted",
                        reason=reasoning,
                    )
            if commit:
                await self.session.commit()
            return existing

        assignment = ContentTagAssignment(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            tag=tag,
            status=status,
            assigned_by_type=assigned_by_type,
            assigned_by_user_id=assigned_by_user_id,
            source=source,
            source_detail=source_detail or {},
            confidence=confidence,
            reasoning=reasoning,
        )
        self.repository.add_assignment(assignment)
        if assigned_by_type == "user" and status == "accepted":
            self._record_feedback(
                owner_user_id=owner_user_id,
                content_object_id=content_object_id,
                target_id=tag.id,
                action="manually_assigned",
                reason=reasoning,
            )
        await self.session.flush()
        if commit:
            await self.session.commit()
        return assignment

    async def replace_manual_tags_for_content(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        tag_names: list[str],
        assigned_by_user_id: str | None,
        commit: bool = False,
    ) -> None:
        desired_tags: dict[str, Tag] = {}
        for raw_name in tag_names:
            clean_name = raw_name.strip()
            if not clean_name:
                continue
            tag = await self.get_or_create_tag(
                owner_user_id=owner_user_id,
                name=clean_name,
                created_by_user_id=assigned_by_user_id,
                created_by_type="user",
                source="manual",
            )
            desired_tags[tag.id] = tag

        active = await self.repository.list_active_assignments_for_content(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            statuses={"suggested", "accepted"},
        )
        for assignment in active:
            if assignment.tag_id not in desired_tags:
                assignment.status = "removed"
                assignment.assigned_by_type = "user"
                assignment.assigned_by_user_id = assigned_by_user_id
                assignment.source = "manual"
        for tag in desired_tags.values():
            await self.assign_tag_to_content(
                owner_user_id=owner_user_id,
                content_object_id=content_object_id,
                tag_id=tag.id,
                assigned_by_user_id=assigned_by_user_id,
                reasoning="Assigned from content tag_names.",
                commit=False,
            )
        if commit:
            await self.session.commit()

    async def remove_tag_from_content(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        tag_id: str,
        assigned_by_user_id: str | None,
    ) -> None:
        await self._get_content_object(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
        )
        assignment = await self.repository.get_active_assignment(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            tag_id=tag_id,
        )
        if assignment is None:
            raise TagNotFoundError
        assignment.status = "removed"
        assignment.assigned_by_type = "user"
        assignment.assigned_by_user_id = assigned_by_user_id
        assignment.source = "manual"
        self._record_feedback(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            target_id=tag_id,
            action="removed",
            reason=None,
        )
        await self.session.commit()

    async def list_tags_for_content(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        statuses: set[str] | None = None,
    ) -> list[ContentTagAssignment]:
        await self._get_content_object(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
        )
        return await self.repository.list_active_assignments_for_content(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            statuses=statuses,
        )

    async def list_jobs_for_content(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
    ) -> list[TaggingJob]:
        await self._get_content_object(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
        )
        return await self.repository.list_jobs_for_content(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
        )

    async def list_active_tags_for_contents(
        self,
        *,
        owner_user_id: str,
        content_object_ids: list[str],
    ) -> dict[str, list[Tag]]:
        assignments = await self.repository.list_active_assignments_for_contents(
            owner_user_id=owner_user_id,
            content_object_ids=content_object_ids,
            statuses={"accepted"},
        )
        result: dict[str, list[Tag]] = {content_id: [] for content_id in content_object_ids}
        for assignment in assignments:
            result.setdefault(assignment.content_object_id, []).append(assignment.tag)
        return result

    async def list_review_suggestions(
        self,
        *,
        owner_user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ContentTagAssignment]:
        return await self.repository.list_review_suggestions(
            owner_user_id=owner_user_id,
            limit=limit,
            offset=offset,
        )

    async def job_metrics(self, *, owner_user_id: str) -> TagsJobMetricsResponse:
        job_rows = await self.session.execute(
            select(TaggingJob.status, func.count(TaggingJob.id))
            .where(TaggingJob.owner_user_id == owner_user_id)
            .group_by(TaggingJob.status)
        )
        pending_suggestions = await self.session.scalar(
            select(func.count(ContentTagAssignment.id)).where(
                ContentTagAssignment.owner_user_id == owner_user_id,
                ContentTagAssignment.status == TagAssignmentStatus.SUGGESTED.value,
            )
        )
        return TagsJobMetricsResponse(
            jobs_by_status=[
                JobStatusCountResponse(status=status, count=count)
                for status, count in job_rows.all()
            ],
            suggestions_pending=int(pending_suggestions or 0),
        )

    async def enqueue_content_tag_suggestions(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        priority: int = 100,
    ) -> TaggingJob:
        if not self.settings.tags_llm_enabled:
            raise TagLLMDisabledError
        await self._get_content_object(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
        )
        return await self.repository.enqueue_job(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            job_type="suggest_content_tags",
            priority=priority,
        )

    async def suggest_tags_for_content(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        max_tags: int,
        persist: bool,
    ) -> list[ContentTagSuggestion]:
        if not self.settings.tags_llm_enabled:
            raise TagLLMDisabledError("LLM tag suggestions are disabled.")
        tagging_input = await self._build_tagging_input(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
        )
        tagger = LLMContentTagger(settings=self.settings, llm_generator=self.llm_generator)
        suggestions = await tagger.suggest(
            title=tagging_input.content_object.title,
            url=self._content_url(tagging_input.content_object),
            existing_tags=[tag.name for tag in tagging_input.existing_tag_candidates],
            excerpt=tagging_input.excerpt,
            metadata={
                "kind": tagging_input.content_object.kind,
                "media_type": tagging_input.content_object.media_type,
                "source_filename": tagging_input.content_object.source_filename,
                "mime_type": tagging_input.content_object.mime_type,
                "size_bytes": tagging_input.content_object.size_bytes,
            },
            max_tags=max_tags,
        )
        suggestions = [
            suggestion
            for suggestion in suggestions
            if suggestion.confidence >= self.settings.tags_llm_suggest_threshold
        ][:max_tags]
        if not persist:
            return suggestions

        source_detail: dict[str, object] = {
            "model": self.settings.tags_llm_model,
            "prompt_version": self.settings.tags_llm_prompt_version,
        }
        mode = await self._tags_auto_apply_mode(owner_user_id=owner_user_id)
        if mode == AutomaticApplyMode.DISABLED:
            return suggestions
        for suggestion in suggestions:
            tag = await self.repository.get_tag_by_slug_or_alias(
                owner_user_id=owner_user_id,
                slug=suggestion.slug,
            )
            if tag is None:
                if not self.settings.tags_llm_create_missing_tags:
                    continue
                tag = await self.create_tag(
                    owner_user_id=owner_user_id,
                    name=suggestion.name,
                    description=None,
                    tag_kind=None,
                    created_by_user_id=None,
                    created_by_type="llm",
                    source="llm_auto_created",
                    source_detail=source_detail,
                    confidence=suggestion.confidence,
                    commit=False,
                )
            if tag.is_archived:
                continue
            assignment_status = (
                TagAssignmentStatus.ACCEPTED.value
                if (
                    mode == AutomaticApplyMode.AUTO_APPLY_HIGH_CONFIDENCE
                    and suggestion.confidence >= self.settings.tags_llm_auto_apply_threshold
                )
                else TagAssignmentStatus.SUGGESTED.value
            )
            await self.assign_tag_to_content(
                owner_user_id=owner_user_id,
                content_object_id=content_object_id,
                tag_id=tag.id,
                assigned_by_user_id=None,
                assigned_by_type="llm",
                source=("llm_auto_applied" if assignment_status == "accepted" else "llm_suggested"),
                source_detail=source_detail,
                confidence=suggestion.confidence,
                reasoning=suggestion.reasoning,
                status=assignment_status,
                commit=False,
            )
        await self.session.flush()
        return suggestions

    async def accept_suggestion(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        assignment_id: str,
        assigned_by_user_id: str,
    ) -> ContentTagAssignment:
        await self._get_content_object(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
        )
        assignment = await self.repository.get_assignment(
            owner_user_id=owner_user_id,
            assignment_id=assignment_id,
        )
        if assignment is None or assignment.content_object_id != content_object_id:
            raise TagNotFoundError
        if assignment.status != "suggested":
            raise TagConflictError
        assignment.status = TagAssignmentStatus.ACCEPTED.value
        assignment.assigned_by_type = "user"
        assignment.assigned_by_user_id = assigned_by_user_id
        self._record_feedback(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            target_id=assignment.tag_id,
            action="accepted",
            reason=assignment.reasoning,
        )
        await self.session.commit()
        return assignment

    async def reject_suggestion(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        assignment_id: str,
        assigned_by_user_id: str,
    ) -> ContentTagAssignment:
        await self._get_content_object(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
        )
        assignment = await self.repository.get_assignment(
            owner_user_id=owner_user_id,
            assignment_id=assignment_id,
        )
        if assignment is None or assignment.content_object_id != content_object_id:
            raise TagNotFoundError
        if assignment.status != "suggested":
            raise TagConflictError
        assignment.status = TagAssignmentStatus.REJECTED.value
        assignment.assigned_by_type = "user"
        assignment.assigned_by_user_id = assigned_by_user_id
        self._record_feedback(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            target_id=assignment.tag_id,
            action="rejected",
            reason=assignment.reasoning,
        )
        await self.session.commit()
        return assignment

    async def process_job(self, job: TaggingJob) -> None:
        if not self.settings.tags_llm_enabled:
            raise TagLLMDisabledError("LLM tag suggestions are disabled.")
        if job.job_type not in {"suggest_content_tags", "refresh_content_tags"}:
            raise TagValidationError(f"Unsupported tagging job type: {job.job_type}")
        if await self._job_is_stale(job):
            job.status = TaggingJobStatusValue.STALE.value
            job.last_error = "Content was updated after the tagging job was enqueued."
            job.locked_at = None
            job.locked_by = None
            return
        await self.suggest_tags_for_content(
            owner_user_id=job.owner_user_id,
            content_object_id=job.content_object_id,
            max_tags=self.settings.tags_llm_max_tags,
            persist=True,
        )
        job.status = TaggingJobStatusValue.SUCCEEDED.value
        job.last_error = None
        job.locked_at = None
        job.locked_by = None

    async def mark_failed(self, job: TaggingJob, error: str) -> None:
        job.last_error = error
        job.locked_at = None
        job.locked_by = None
        if error == "LLM tag suggestions are disabled." or job.attempts >= job.max_attempts:
            job.status = TaggingJobStatusValue.FAILED.value
            return
        job.status = TaggingJobStatusValue.PENDING.value
        job.run_after = datetime.now(UTC) + timedelta(seconds=min(300, 2**job.attempts))

    async def merge_tags(
        self,
        *,
        owner_user_id: str,
        source_tag_id: str,
        target_tag_id: str,
        assigned_by_user_id: str,
    ) -> Tag:
        if source_tag_id == target_tag_id:
            raise TagConflictError
        source = await self._get_tag(owner_user_id=owner_user_id, tag_id=source_tag_id)
        target = await self._get_tag(owner_user_id=owner_user_id, tag_id=target_tag_id)
        if target.is_archived:
            raise TagConflictError
        assignments = await self.session.scalars(
            select(ContentTagAssignment).where(
                ContentTagAssignment.owner_user_id == owner_user_id,
                ContentTagAssignment.tag_id == source.id,
                ContentTagAssignment.status.in_(("suggested", "accepted")),
            )
        )
        for assignment in assignments:
            existing = await self.repository.get_active_assignment(
                owner_user_id=owner_user_id,
                content_object_id=assignment.content_object_id,
                tag_id=target.id,
            )
            if existing is not None:
                assignment.status = TagAssignmentStatus.REMOVED.value
            else:
                assignment.tag_id = target.id
            self._record_feedback(
                owner_user_id=owner_user_id,
                content_object_id=assignment.content_object_id,
                target_id=target.id,
                action="changed",
                previous_target_id=source.id,
                new_target_id=target.id,
                reason="Tag merge.",
                source="system",
            )
        source.is_archived = True
        target.aliases = self._normalize_aliases(
            [*target.aliases, source.slug, source.name, *source.aliases],
            primary_name=target.name,
        )
        source.updated_at = datetime.now(UTC)
        target.updated_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(target)
        return target

    async def _build_tagging_input(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
    ) -> TaggingInput:
        content_object = await self._get_content_object(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
        )
        active = await self.repository.list_active_assignments_for_content(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            statuses={"accepted"},
        )
        all_tags = await self.repository.list_tags(
            owner_user_id=owner_user_id,
            include_archived=False,
        )
        active_tags = [assignment.tag for assignment in active]
        excerpt = await self._text_excerpt(content_object, max_chars=4000)
        return TaggingInput(
            content_object=content_object,
            active_tags=active_tags,
            existing_tag_candidates=self._existing_tag_candidates(
                content_object=content_object,
                active_tags=active_tags,
                tags=all_tags,
                text_excerpt=excerpt,
                max_tags=24,
            ),
            excerpt=excerpt,
        )

    async def _get_tag(self, *, owner_user_id: str, tag_id: str) -> Tag:
        tag = await self.repository.get_tag(owner_user_id=owner_user_id, tag_id=tag_id)
        if tag is None:
            raise TagNotFoundError
        return tag

    async def _get_content_object(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
    ) -> ContentObject:
        content_object = await self.content.get_by_id(
            owner_user_id=owner_user_id,
            object_id=content_object_id,
        )
        if content_object is None:
            raise TagNotFoundError
        return content_object

    async def _job_is_stale(self, job: TaggingJob) -> bool:
        if job.content_updated_at_snapshot is None:
            return False
        content_object = await self._get_content_object(
            owner_user_id=job.owner_user_id,
            content_object_id=job.content_object_id,
        )
        return content_object.updated_at > job.content_updated_at_snapshot

    async def _tags_auto_apply_mode(self, *, owner_user_id: str) -> AutomaticApplyMode:
        settings = await self.session.scalar(
            select(TaxonomyUserSettings).where(TaxonomyUserSettings.owner_user_id == owner_user_id)
        )
        if settings is None:
            return AutomaticApplyMode.AUTO_APPLY_HIGH_CONFIDENCE
        try:
            return AutomaticApplyMode(settings.tags_auto_apply_mode)
        except ValueError:
            return AutomaticApplyMode.AUTO_APPLY_HIGH_CONFIDENCE

    async def _ensure_aliases_available(
        self,
        *,
        owner_user_id: str,
        aliases: list[str],
        except_tag_id: str | None = None,
    ) -> None:
        for alias in aliases:
            existing = await self.repository.get_tag_by_slug_or_alias(
                owner_user_id=owner_user_id,
                slug=alias,
            )
            if existing is not None and existing.id != except_tag_id:
                raise TagConflictError

    def _record_feedback(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        target_id: str | None,
        action: str,
        reason: str | None,
        previous_target_id: str | None = None,
        new_target_id: str | None = None,
        source: str = "user",
    ) -> None:
        self.session.add(
            ClassificationFeedback(
                owner_user_id=owner_user_id,
                content_object_id=content_object_id,
                target_type="tag",
                target_id=target_id,
                action=action,
                previous_target_id=previous_target_id,
                new_target_id=new_target_id,
                reason=reason,
                source=source,
            )
        )

    @staticmethod
    def _validate_name(name: str) -> str:
        clean_name = name.strip()
        if not clean_name:
            raise TagValidationError("Tag name must not be empty.")
        return clean_name

    @staticmethod
    def _normalize_aliases(aliases: list[str], *, primary_name: str) -> list[str]:
        primary_slug = slugify(primary_name)
        normalized = []
        for alias in aliases:
            alias_slug = slugify(alias)
            if not alias_slug or alias_slug == primary_slug:
                continue
            normalized.append(alias_slug)
        return list(dict.fromkeys(normalized))

    async def _text_excerpt(self, content_object: ContentObject, *, max_chars: int) -> str | None:
        parts: list[str] = []
        for asset in content_object.assets:
            if asset.text_content is not None and asset.text_content.strip():
                parts.append(asset.text_content.strip())
                continue
            if asset.media_type != "text":
                snapshot_text = await self.snapshots.get_markdown_text(
                    source_asset_id=asset.id,
                    max_chars=max_chars,
                )
                if snapshot_text:
                    parts.append(snapshot_text.strip())
        text = "\n\n".join(parts).strip()
        text = TagsService._strip_filename_heading(text)
        return text[:max_chars] if text else None

    @staticmethod
    def _content_url(content_object: ContentObject) -> str | None:
        if content_object.media_type == "link":
            return content_object.source_filename
        return None

    @classmethod
    def _existing_tag_candidates(
        cls,
        *,
        content_object: ContentObject,
        active_tags: list[Tag],
        tags: list[Tag],
        text_excerpt: str | None = None,
        max_tags: int,
    ) -> list[Tag]:
        active_by_slug = {tag.slug: tag for tag in active_tags}
        text_excerpt = text_excerpt or cls._text_excerpt_from_loaded_assets(content_object)
        text = cls._candidate_matching_text(content_object, text_excerpt=text_excerpt)
        scored: list[tuple[int, str, Tag]] = []
        for tag in tags:
            if tag.slug in active_by_slug:
                scored.append((10_000, tag.name.casefold(), tag))
                continue
            score = cls._tag_match_score(tag=tag, text=text)
            if score > 0:
                scored.append((score, tag.name.casefold(), tag))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return [tag for _, _, tag in scored[:max_tags]]

    @staticmethod
    def _text_excerpt_from_loaded_assets(content_object: ContentObject) -> str | None:
        parts = [
            asset.text_content.strip()
            for asset in content_object.assets
            if asset.text_content is not None and asset.text_content.strip()
        ]
        text = "\n\n".join(parts).strip()
        text = TagsService._strip_filename_heading(text)
        return text or None

    @classmethod
    def _candidate_matching_text(
        cls,
        content_object: ContentObject,
        *,
        text_excerpt: str | None = None,
    ) -> str:
        parts = [
            cls._semantic_title(content_object.title),
            text_excerpt,
        ]
        if content_object.media_type == "link":
            parts.append(content_object.source_filename)
        return " ".join(part for part in parts if part).casefold()

    @staticmethod
    def _tag_match_score(*, tag: Tag, text: str) -> int:
        candidates = [
            tag.name,
            tag.slug,
            *(tag.aliases or []),
            tag.description or "",
            tag.tag_kind or "",
        ]
        score = 0
        for candidate in candidates:
            normalized = candidate.strip().casefold()
            if not normalized:
                continue
            if normalized in text:
                score += 20
            tokens = {
                token for token in re.split(r"[^0-9a-zA-Zа-яА-ЯёЁ]+", normalized) if len(token) >= 3
            }
            score += sum(1 for token in tokens if token in text)
        return score

    @classmethod
    def _semantic_title(cls, title: str) -> str | None:
        return None if cls._looks_like_filename_heading(title) else title

    @classmethod
    def _strip_filename_heading(cls, text: str) -> str:
        lines = text.splitlines()
        if not lines:
            return text
        first_content_index = next(
            (index for index, line in enumerate(lines) if line.strip()), None
        )
        if first_content_index is None:
            return ""
        first_line = lines[first_content_index].strip()
        if not cls._looks_like_filename_heading(first_line):
            return text
        del lines[first_content_index]
        return "\n".join(lines).strip()

    @staticmethod
    def _looks_like_filename_heading(line: str) -> bool:
        text = line.strip().lstrip("#").strip()
        return bool(re.fullmatch(r"[\w .()\-\u0400-\u04FF]+\.[A-Za-z0-9]{1,8}", text))
