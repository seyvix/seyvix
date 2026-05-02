from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.modules.content.infrastructure.repositories import ContentRepository
from app.modules.content.models import ContentObject
from app.modules.content.storage import slugify
from app.modules.llm.contracts import StructuredLLMGenerator, build_structured_llm_generator
from app.modules.tags.contracts import ContentTagSuggestion
from app.modules.tags.infrastructure.llm_tagger import LLMContentTagger
from app.modules.tags.infrastructure.repositories import TagsRepository
from app.modules.tags.models import ContentTagAssignment, Tag, TaggingJob


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
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.repository = TagsRepository(session)
        self.content = ContentRepository(session)
        self.llm_generator = llm_generator or build_structured_llm_generator()

    async def create_tag(
        self,
        *,
        owner_user_id: str,
        name: str,
        description: str | None,
        tag_kind: str | None,
        created_by_user_id: str | None,
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
        existing = await self.repository.get_tag_by_slug(
            owner_user_id=owner_user_id,
            slug=tag_slug,
        )
        if existing is not None:
            raise TagConflictError
        tag = Tag(
            owner_user_id=owner_user_id,
            name=clean_name,
            slug=tag_slug,
            description=description,
            tag_kind=tag_kind,
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
        existing = await self.repository.get_tag_by_slug(
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
                existing.status = "accepted"
                existing.assigned_by_user_id = assigned_by_user_id
                existing.reasoning = reasoning or existing.reasoning
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
        for suggestion in suggestions:
            tag = await self.repository.get_tag_by_slug(
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
                "accepted"
                if suggestion.confidence >= self.settings.tags_llm_auto_apply_threshold
                else "suggested"
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
        assignment.status = "accepted"
        assignment.assigned_by_type = "user"
        assignment.assigned_by_user_id = assigned_by_user_id
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
        assignment.status = "rejected"
        assignment.assigned_by_type = "user"
        assignment.assigned_by_user_id = assigned_by_user_id
        await self.session.commit()
        return assignment

    async def process_job(self, job: TaggingJob) -> None:
        if not self.settings.tags_llm_enabled:
            raise TagLLMDisabledError("LLM tag suggestions are disabled.")
        if job.job_type not in {"suggest_content_tags", "refresh_content_tags"}:
            raise TagValidationError(f"Unsupported tagging job type: {job.job_type}")
        await self.suggest_tags_for_content(
            owner_user_id=job.owner_user_id,
            content_object_id=job.content_object_id,
            max_tags=self.settings.tags_llm_max_tags,
            persist=True,
        )
        job.status = "succeeded"
        job.last_error = None
        job.locked_at = None
        job.locked_by = None

    async def mark_failed(self, job: TaggingJob, error: str) -> None:
        job.last_error = error
        job.locked_at = None
        job.locked_by = None
        if error == "LLM tag suggestions are disabled." or job.attempts >= job.max_attempts:
            job.status = "failed"
            return
        job.status = "pending"
        job.run_after = datetime.now(UTC) + timedelta(seconds=min(300, 2**job.attempts))

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
        return TaggingInput(
            content_object=content_object,
            active_tags=active_tags,
            existing_tag_candidates=self._existing_tag_candidates(
                content_object=content_object,
                active_tags=active_tags,
                tags=all_tags,
                max_tags=24,
            ),
            excerpt=self._text_excerpt(content_object, max_chars=4000),
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

    @staticmethod
    def _validate_name(name: str) -> str:
        clean_name = name.strip()
        if not clean_name:
            raise TagValidationError("Tag name must not be empty.")
        return clean_name

    @staticmethod
    def _text_excerpt(content_object: ContentObject, *, max_chars: int) -> str | None:
        text = "\n".join(
            asset.text_content.strip()
            for asset in content_object.assets
            if asset.text_content is not None and asset.text_content.strip()
        ).strip()
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
        max_tags: int,
    ) -> list[Tag]:
        active_by_slug = {tag.slug: tag for tag in active_tags}
        text = cls._candidate_matching_text(content_object)
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

    @classmethod
    def _candidate_matching_text(cls, content_object: ContentObject) -> str:
        parts = [
            cls._semantic_title(content_object.title),
            cls._text_excerpt(content_object, max_chars=4000),
        ]
        if content_object.media_type == "link":
            parts.append(content_object.source_filename)
        return " ".join(part for part in parts if part).casefold()

    @staticmethod
    def _tag_match_score(*, tag: Tag, text: str) -> int:
        candidates = [tag.name, tag.slug, tag.description or "", tag.tag_kind or ""]
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
