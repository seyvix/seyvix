from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol, cast
from uuid import uuid4

from app.contracts.events import EventEnvelope, TaxonomyClassificationCompletedPayload
from app.core.config import Settings, get_settings
from app.modules.llm.contracts import (
    LLMGenerationError,
    StructuredLLMGenerator,
    build_structured_llm_generator,
)
from app.modules.content.models import ContentObject
from app.modules.search.schemas import SemanticSearchResult
from app.modules.taxonomy.infrastructure.repositories import TaxonomyRepository
from app.modules.taxonomy.models import (
    TaxonomyCategory,
    TaxonomyCategoryProfile,
    TaxonomyClassificationJob,
    TaxonomyContentAssignment,
    TaxonomyTemplate,
    TaxonomyTemplateCategory,
    TaxonomyUserSettings,
)
from app.modules.taxonomy.schemas import (
    TaxonomyAssignmentResponse,
    TaxonomyBreadcrumbResponse,
    TaxonomyCategoryDeleteResponse,
    TaxonomyCategoryResponse,
    TaxonomyCategoryTreeItem,
    TaxonomyClassificationCandidateResponse,
    TaxonomyClassificationCategoryResponse,
    TaxonomyClassificationResponse,
    TaxonomyInboxReclassifyResponse,
    TaxonomyLLMDecisionResponse,
    TaxonomyProfileDraftResponse,
    TaxonomyProfileResponse,
    TaxonomySettingsResponse,
    TaxonomyTemplateDetailResponse,
    TaxonomyTemplateSummaryResponse,
    TaxonomyTemplateTreeItem,
)
from app.modules.vectorization.contracts import (
    VectorizationSubject,
    build_taxonomy_category_profile_vector_subject,
)
from app.modules.vectorization.models import VectorizationJob
from app.platform.events.outbox import EventOutboxRepository
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

SLUG_PATTERN = re.compile(r"^[a-z0-9_-]+$")
LLM_JUDGE_PROMPT_VERSION = "taxonomy_classification_llm_judge_v1"


class TaxonomyNotFoundError(Exception):
    pass


class TaxonomyConflictError(Exception):
    pass


class TaxonomyValidationError(Exception):
    pass


class TaxonomyLLMClassificationError(Exception):
    pass


class TaxonomyPermissionError(Exception):
    pass


class SemanticClassificationSearchService(Protocol):
    async def semantic_search(
        self,
        *,
        owner_user_id: str,
        query: str,
        limit: int,
        source: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
    ) -> list[SemanticSearchResult]:
        raise NotImplementedError


@dataclass(slots=True)
class InitializeTaxonomyResult:
    owner_user_id: str
    template_slug: str
    created_categories_count: int
    created_profiles_count: int


@dataclass(frozen=True, slots=True)
class InterestOption:
    slug: str
    name: str
    description: str


@dataclass(slots=True)
class ClassificationCandidate:
    result: SemanticSearchResult
    category: TaxonomyCategory
    profile: TaxonomyCategoryProfile | None


class _GeneratedInterestNode(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    children: list[_GeneratedInterestNode] = Field(default_factory=list, max_length=8)


class _GeneratedProfileDraft(BaseModel):
    summary: str | None = None
    keywords: list[str] = Field(default_factory=list, max_length=20)
    positive_examples: list[str] = Field(default_factory=list, max_length=20)
    negative_examples: list[str] = Field(default_factory=list, max_length=20)
    reasoning: str = Field(min_length=1, max_length=2000)


class TaxonomyService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings | None = None,
        llm_generator: StructuredLLMGenerator | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.llm_generator = llm_generator or build_structured_llm_generator()
        self.repository = TaxonomyRepository(session)
        self.outbox = EventOutboxRepository(session)

    async def create_category(
        self,
        *,
        owner_user_id: str,
        parent_id: str | None,
        slug: str,
        name: str,
        description: str | None,
        sort_order: int,
        source: str = "user",
        is_system: bool = False,
        commit: bool = True,
    ) -> TaxonomyCategory:
        slug = self._validate_slug(slug)
        name = self._validate_name(name)
        parent = None
        if parent_id is not None:
            parent = await self.repository.get_category(
                owner_user_id=owner_user_id,
                category_id=parent_id,
            )
            if parent is None:
                raise TaxonomyNotFoundError
            if parent.is_archived:
                raise TaxonomyConflictError

        path = f"{parent.path}/{slug}" if parent is not None else slug
        depth = parent.depth + 1 if parent is not None else 0
        await self._ensure_unique_category(
            owner_user_id=owner_user_id,
            parent_id=parent_id,
            slug=slug,
            path=path,
        )
        category = TaxonomyCategory(
            owner_user_id=owner_user_id,
            parent_id=parent_id,
            slug=slug,
            name=name,
            description=description,
            path=path,
            depth=depth,
            sort_order=sort_order,
            source=source,
            is_system=is_system,
        )
        self.repository.add_category(category)
        await self.session.flush()
        if commit:
            await self.session.commit()
            await self.session.refresh(category)
        return category

    async def ensure_category_path(
        self,
        *,
        owner_user_id: str,
        raw_path: str | None,
        source: str = "user",
        commit: bool = False,
    ) -> TaxonomyCategory | None:
        if not raw_path:
            return None
        segments = [self._slugify_path_segment(segment) for segment in raw_path.split("/")]
        segments = [segment for segment in segments if segment]
        if not segments:
            return None

        parent: TaxonomyCategory | None = None
        current_path = ""
        for segment in segments:
            current_path = f"{current_path}/{segment}".strip("/")
            category = await self.repository.get_category_by_path(
                owner_user_id=owner_user_id,
                path=current_path,
            )
            if category is None:
                category = await self.create_category(
                    owner_user_id=owner_user_id,
                    parent_id=parent.id if parent is not None else None,
                    slug=segment,
                    name=segment,
                    description=None,
                    sort_order=100,
                    source=source,
                    commit=False,
                )
            parent = category
        if commit:
            await self.session.commit()
        return parent

    async def get_category(self, *, owner_user_id: str, category_id: str) -> TaxonomyCategory:
        category = await self.repository.get_category(
            owner_user_id=owner_user_id,
            category_id=category_id,
        )
        if category is None:
            raise TaxonomyNotFoundError
        return category

    async def search_categories(
        self,
        *,
        owner_user_id: str,
        query_text: str,
        include_archived: bool,
    ) -> list[TaxonomyCategory]:
        query_text = query_text.strip()
        if not query_text:
            raise TaxonomyValidationError
        return await self.repository.search_categories(
            owner_user_id=owner_user_id,
            query_text=query_text,
            include_archived=include_archived,
        )

    async def get_breadcrumbs(
        self,
        *,
        owner_user_id: str,
        category_id: str,
    ) -> list[TaxonomyBreadcrumbResponse]:
        category = await self.get_category(owner_user_id=owner_user_id, category_id=category_id)
        prefixes = [
            "/".join(category.path.split("/")[: index + 1])
            for index in range(len(category.path.split("/")))
        ]
        categories = await self.repository.list_categories(
            owner_user_id=owner_user_id,
            include_archived=True,
        )
        by_path = {item.path: item for item in categories}
        return [
            TaxonomyBreadcrumbResponse(id=by_path[path].id, name=by_path[path].name, path=path)
            for path in prefixes
            if path in by_path
        ]

    async def update_category(
        self,
        *,
        owner_user_id: str,
        category_id: str,
        name: str | None,
        description: str | None,
        slug: str | None,
        sort_order: int | None,
        is_archived: bool | None,
    ) -> TaxonomyCategory:
        category = await self.get_category(owner_user_id=owner_user_id, category_id=category_id)
        if name is not None:
            category.name = self._validate_name(name)
        if description is not None:
            category.description = description
        if sort_order is not None:
            category.sort_order = sort_order
        if is_archived is not None:
            category.is_archived = is_archived
        if slug is not None and slug != category.slug:
            if await self.repository.has_children(
                owner_user_id=owner_user_id,
                category_id=category.id,
                active_only=False,
            ):
                raise TaxonomyConflictError
            new_slug = self._validate_slug(slug)
            parent_path = category.path.rsplit("/", 1)[0] if "/" in category.path else ""
            new_path = f"{parent_path}/{new_slug}".strip("/")
            await self._ensure_unique_category(
                owner_user_id=owner_user_id,
                parent_id=category.parent_id,
                slug=new_slug,
                path=new_path,
                except_category_id=category.id,
            )
            category.slug = new_slug
            category.path = new_path
        await self._enqueue_category_profile_index(
            owner_user_id=owner_user_id,
            category_id=category.id,
            priority=50,
        )
        await self.session.commit()
        await self.session.refresh(category)
        return category

    async def archive_category(self, *, owner_user_id: str, category_id: str) -> None:
        category = await self.get_category(owner_user_id=owner_user_id, category_id=category_id)
        if category.is_system:
            raise TaxonomyConflictError
        if await self.repository.has_children(
            owner_user_id=owner_user_id,
            category_id=category_id,
            active_only=True,
        ):
            raise TaxonomyConflictError
        category.is_archived = True
        await self.session.commit()

    async def delete_category(
        self,
        *,
        owner_user_id: str,
        category_id: str,
        delete_notes: bool,
        confirm_category_name: str | None,
        confirm_delete_notes_text: str | None,
    ) -> TaxonomyCategoryDeleteResponse:
        category = await self.get_category(owner_user_id=owner_user_id, category_id=category_id)
        if category.is_system:
            raise TaxonomyConflictError
        if delete_notes and (
            confirm_category_name != category.name or confirm_delete_notes_text != "DELETE_NOTES"
        ):
            raise TaxonomyValidationError
        inbox = await self.repository.get_category_by_path(
            owner_user_id=owner_user_id,
            path="inbox",
            include_archived=False,
        )
        if inbox is None:
            raise TaxonomyNotFoundError

        categories = await self.repository.list_categories(
            owner_user_id=owner_user_id,
            include_archived=False,
        )
        subtree = [
            item
            for item in categories
            if item.path == category.path or item.path.startswith(f"{category.path}/")
        ]
        subtree_paths = {item.path for item in subtree}
        current_assignments = await self.repository.list_current_assignments(
            owner_user_id=owner_user_id
        )
        affected_assignments = [
            assignment
            for assignment in current_assignments
            if assignment.category_path_snapshot in subtree_paths
        ]

        deleted_notes_count = 0
        moved_notes_count = 0
        if delete_notes:
            content_ids = [assignment.content_object_id for assignment in affected_assignments]
            if content_ids:
                slugs = list(
                    await self.session.scalars(
                        select(ContentObject.slug).where(
                            ContentObject.owner_user_id == owner_user_id,
                            ContentObject.id.in_(content_ids),
                        )
                    )
                )
                if slugs:
                    from app.modules.content.service import ContentService

                    await ContentService(self.session).delete_notes(
                        owner_user_id=owner_user_id,
                        slugs=slugs,
                    )
                    deleted_notes_count = len(slugs)
        else:
            for assignment in affected_assignments:
                await self._create_current_assignment(
                    owner_user_id=owner_user_id,
                    content_object_id=assignment.content_object_id,
                    category=inbox,
                    status="accepted",
                    assigned_by="system",
                    confidence=1.0,
                    reasoning=f"Category {category.path} was deleted; moved to inbox.",
                    commit=False,
                )
                moved_notes_count += 1

        for item in sorted(subtree, key=lambda node: node.depth, reverse=True):
            item.is_archived = True
        await self.session.commit()
        return TaxonomyCategoryDeleteResponse(
            category_id=category.id,
            archived_categories_count=len(subtree),
            moved_notes_count=moved_notes_count,
            deleted_notes_count=deleted_notes_count,
        )

    async def restore_category(
        self,
        *,
        owner_user_id: str,
        category_id: str,
    ) -> TaxonomyCategory:
        category = await self.get_category(owner_user_id=owner_user_id, category_id=category_id)
        if category.parent_id is not None:
            parent = await self.repository.get_category(
                owner_user_id=owner_user_id,
                category_id=category.parent_id,
            )
            if parent is None or parent.is_archived:
                raise TaxonomyConflictError
        category.is_archived = False
        await self.session.commit()
        await self.session.refresh(category)
        return category

    async def get_tree(
        self,
        *,
        owner_user_id: str,
        root_id: str | None,
        max_depth: int | None,
        include_archived: bool,
    ) -> list[TaxonomyCategoryTreeItem]:
        categories = await self.repository.list_categories(
            owner_user_id=owner_user_id,
            include_archived=include_archived,
        )
        if root_id is not None and root_id not in {category.id for category in categories}:
            raise TaxonomyNotFoundError

        by_parent: dict[str | None, list[TaxonomyCategory]] = {}
        for category in categories:
            by_parent.setdefault(category.parent_id, []).append(category)
        for children in by_parent.values():
            children.sort(key=lambda item: (item.sort_order, item.name.casefold()))

        if root_id is None:
            roots = by_parent.get(None, [])
            base_depth = 0
        else:
            root = next(category for category in categories if category.id == root_id)
            roots = [root]
            base_depth = root.depth

        def build(category: TaxonomyCategory) -> TaxonomyCategoryTreeItem:
            children: list[TaxonomyCategoryTreeItem] = []
            if max_depth is None or category.depth - base_depth < max_depth:
                children = [build(child) for child in by_parent.get(category.id, [])]
            return TaxonomyCategoryTreeItem(
                id=category.id,
                name=category.name,
                slug=category.slug,
                path=category.path,
                depth=category.depth,
                description=category.description,
                is_system=category.is_system,
                is_archived=category.is_archived,
                children=children,
            )

        return [build(category) for category in roots]

    async def get_profile(
        self,
        *,
        owner_user_id: str,
        category_id: str,
    ) -> TaxonomyCategoryProfile:
        await self.get_category(owner_user_id=owner_user_id, category_id=category_id)
        profile = await self.repository.get_profile(category_id=category_id)
        if profile is None:
            raise TaxonomyNotFoundError
        return profile

    async def get_user_settings(self, *, owner_user_id: str) -> TaxonomyUserSettings:
        settings = await self.repository.get_settings(owner_user_id=owner_user_id)
        if settings is not None:
            return settings
        settings = TaxonomyUserSettings(owner_user_id=owner_user_id)
        self.repository.add_settings(settings)
        await self.session.commit()
        await self.session.refresh(settings)
        return settings

    async def update_user_settings(
        self,
        *,
        owner_user_id: str,
        category_profile_editing_enabled: bool | None,
        trash_enabled: bool | None,
        trash_retention_days: int | None,
    ) -> TaxonomyUserSettings:
        settings = await self.get_user_settings(owner_user_id=owner_user_id)
        if category_profile_editing_enabled is not None:
            settings.category_profile_editing_enabled = category_profile_editing_enabled
        if trash_enabled is not None:
            settings.trash_enabled = trash_enabled
        if trash_retention_days is not None:
            settings.trash_retention_days = trash_retention_days
        await self.session.commit()
        await self.session.refresh(settings)
        return settings

    async def put_profile(
        self,
        *,
        owner_user_id: str,
        category_id: str,
        summary: str | None,
        keywords: list[str],
        positive_examples: list[str],
        negative_examples: list[str],
    ) -> TaxonomyCategoryProfile:
        settings = await self.get_user_settings(owner_user_id=owner_user_id)
        if not settings.category_profile_editing_enabled:
            raise TaxonomyPermissionError
        await self.get_category(owner_user_id=owner_user_id, category_id=category_id)
        profile = await self.repository.get_profile(category_id=category_id)
        if profile is None:
            profile = TaxonomyCategoryProfile(category_id=category_id)
            self.repository.add_profile(profile)
        profile.summary = summary
        profile.keywords = keywords
        profile.positive_examples = positive_examples
        profile.negative_examples = negative_examples
        await self._enqueue_category_profile_index(
            owner_user_id=owner_user_id,
            category_id=category_id,
            priority=100,
        )
        await self.session.commit()
        await self.session.refresh(profile)
        return profile

    async def suggest_profile_improvement(
        self,
        *,
        owner_user_id: str,
        category_id: str,
        user_guidance: str,
    ) -> TaxonomyProfileDraftResponse:
        category = await self.get_category(owner_user_id=owner_user_id, category_id=category_id)
        profile = await self.repository.get_profile(category_id=category_id)
        children = [
            item
            for item in await self.repository.list_categories(
                owner_user_id=owner_user_id,
                include_archived=False,
            )
            if item.parent_id == category.id
        ]
        prompt = self._build_profile_improvement_prompt(
            category=category,
            profile=profile,
            children=children,
            user_guidance=user_guidance,
        )
        try:
            raw = await self.llm_generator.generate_structured(
                prompt=prompt,
                schema=_GeneratedProfileDraft.model_json_schema(),
                model_config={
                    "model": self.settings.taxonomy_llm_classification_model,
                    "prompt_version": "taxonomy_profile_improvement_v1",
                },
            )
            draft = _GeneratedProfileDraft.model_validate(raw)
        except (LLMGenerationError, ValidationError) as exc:
            raise TaxonomyLLMClassificationError("LLM profile improvement failed.") from exc
        return TaxonomyProfileDraftResponse(
            summary=draft.summary,
            keywords=draft.keywords,
            positive_examples=draft.positive_examples,
            negative_examples=draft.negative_examples,
            reasoning=draft.reasoning,
        )

    async def build_category_profile_document(
        self,
        *,
        owner_user_id: str,
        category_id: str,
    ) -> str:
        category = await self.get_category(owner_user_id=owner_user_id, category_id=category_id)
        profile = await self.repository.get_profile(category_id=category.id)
        breadcrumbs = await self.get_breadcrumbs(
            owner_user_id=owner_user_id, category_id=category_id
        )
        lines = [
            f"Path: {' / '.join(item.name for item in breadcrumbs)}",
            f"Name: {category.name}",
            f"Description: {category.description or ''}",
            f"Summary: {profile.summary if profile is not None and profile.summary else ''}",
            "Keywords: "
            + (", ".join(profile.keywords) if profile is not None and profile.keywords else ""),
            "Positive examples:",
        ]
        if profile is not None:
            lines.extend(f"- {example}" for example in profile.positive_examples)
        lines.append("Negative examples:")
        if profile is not None:
            lines.extend(f"- {example}" for example in profile.negative_examples)
        return "\n".join(lines)

    async def build_category_profile_vector_subject(
        self,
        *,
        owner_user_id: str,
        category_id: str,
    ) -> VectorizationSubject:
        category = await self.get_category(owner_user_id=owner_user_id, category_id=category_id)
        profile = await self.repository.get_profile(category_id=category.id)
        source_updated_at = category.updated_at
        if profile is not None and profile.updated_at > source_updated_at:
            source_updated_at = profile.updated_at
        document = await self.build_category_profile_document(
            owner_user_id=owner_user_id,
            category_id=category_id,
        )
        return build_taxonomy_category_profile_vector_subject(
            owner_user_id=owner_user_id,
            category_id=category.id,
            category_path=category.path,
            category_depth=category.depth,
            source_text=document,
            source_updated_at=source_updated_at,
        )

    async def create_manual_assignment(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        category_id: str,
        reasoning: str | None,
        commit: bool = True,
    ) -> TaxonomyContentAssignment:
        content_object = await self.repository.get_content_object(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
        )
        if content_object is None:
            raise TaxonomyNotFoundError
        category = await self.repository.get_category(
            owner_user_id=owner_user_id,
            category_id=category_id,
            include_archived=False,
        )
        if category is None:
            raise TaxonomyNotFoundError
        return await self._create_current_assignment(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            category=category,
            status="accepted",
            assigned_by="user",
            confidence=1.0,
            reasoning=reasoning,
            commit=commit,
        )

    async def assign_content_to_path(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        raw_path: str | None,
        reasoning: str | None,
        commit: bool = False,
    ) -> TaxonomyContentAssignment | None:
        category = await self.ensure_category_path(
            owner_user_id=owner_user_id,
            raw_path=raw_path,
            source="user",
            commit=False,
        )
        if category is None:
            return None
        return await self.create_manual_assignment(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            category_id=category.id,
            reasoning=reasoning,
            commit=commit,
        )

    async def enqueue_classification_job(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        priority: int = 100,
        source_event_id: str | None = None,
        correlation_id: str | None = None,
    ) -> TaxonomyClassificationJob:
        await self._ensure_content_exists(owner_user_id, content_object_id)
        return await self.repository.enqueue_classification_job(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            job_type="classify_content",
            priority=priority,
            source_event_id=source_event_id,
            correlation_id=correlation_id,
        )

    async def list_assignments(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
    ) -> list[TaxonomyContentAssignment]:
        await self._ensure_content_exists(owner_user_id, content_object_id)
        return await self.repository.list_assignments(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
        )

    async def get_current_assignment(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
    ) -> TaxonomyContentAssignment | None:
        await self._ensure_content_exists(owner_user_id, content_object_id)
        return await self.repository.get_current_assignment(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
        )

    async def list_classification_jobs(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
    ) -> list[TaxonomyClassificationJob]:
        await self._ensure_content_exists(owner_user_id, content_object_id)
        return await self.repository.list_classification_jobs_for_content(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
        )

    async def enqueue_inbox_reclassification_jobs(
        self,
        *,
        owner_user_id: str,
    ) -> TaxonomyInboxReclassifyResponse:
        inbox = await self.repository.get_category_by_path(
            owner_user_id=owner_user_id,
            path="inbox",
            include_archived=False,
        )
        if inbox is None:
            raise TaxonomyNotFoundError
        assignments = await self.repository.list_current_assignments(owner_user_id=owner_user_id)
        enqueued_count = 0
        for assignment in assignments:
            if assignment.category_path_snapshot != "inbox":
                continue
            await self.enqueue_classification_job(
                owner_user_id=owner_user_id,
                content_object_id=assignment.content_object_id,
                priority=20,
                source_event_id=None,
                correlation_id=str(uuid4()),
            )
            enqueued_count += 1
        await self.session.commit()
        return TaxonomyInboxReclassifyResponse(enqueued_count=enqueued_count)

    async def accept_assignment(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        assignment_id: str,
    ) -> TaxonomyContentAssignment:
        assignment = await self._load_assignment(owner_user_id, content_object_id, assignment_id)
        category = await self.repository.get_category(
            owner_user_id=owner_user_id,
            category_id=assignment.category_id,
            include_archived=False,
        )
        if category is None:
            raise TaxonomyConflictError
        await self.repository.override_current_assignments(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            except_assignment_id=assignment.id,
        )
        assignment.status = "accepted"
        assignment.is_current = True
        assignment.category_name_snapshot = category.name
        assignment.category_path_snapshot = category.path
        await self.session.commit()
        await self.session.refresh(assignment)
        return assignment

    async def reject_assignment(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        assignment_id: str,
    ) -> TaxonomyContentAssignment:
        assignment = await self._load_assignment(owner_user_id, content_object_id, assignment_id)
        assignment.status = "rejected"
        assignment.is_current = False
        await self.session.commit()
        await self.session.refresh(assignment)
        return assignment

    async def classify_content_object(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        semantic_search_service: SemanticClassificationSearchService | None = None,
        limit: int = 5,
    ) -> TaxonomyContentAssignment | None:
        response = await self.classify_content_object_with_response(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            mode="semantic_only",
            candidate_limit=limit,
            dry_run=False,
            semantic_search_service=semantic_search_service,
        )
        if response.assignment_id is None:
            return None
        assignment = await self.repository.get_assignment(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            assignment_id=response.assignment_id,
        )
        if assignment is None:
            raise TaxonomyNotFoundError
        return assignment

    async def classify_content_object_with_response(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        mode: Literal["semantic_only", "llm_judge"],
        candidate_limit: int,
        dry_run: bool,
        semantic_search_service: SemanticClassificationSearchService | None = None,
    ) -> TaxonomyClassificationResponse:
        from app.modules.content.service import ContentService, NoteNotFoundError
        from app.modules.search.service import SemanticSearchService

        try:
            classification_input = await ContentService(self.session).build_classification_input(
                owner_user_id=owner_user_id,
                content_object_id=content_object_id,
                text_excerpt_max_chars=4000,
            )
        except NoteNotFoundError as exc:
            raise TaxonomyNotFoundError from exc

        query = self._build_classification_query(
            title=classification_input.title,
            url=classification_input.url,
            tags=classification_input.tags,
            text_excerpt=classification_input.text_excerpt,
        )
        search_service = semantic_search_service or SemanticSearchService(self.session)
        search_results = await search_service.semantic_search(
            owner_user_id=owner_user_id,
            query=query,
            source="taxonomy",
            source_type="category_profile",
            source_id=None,
            limit=candidate_limit,
        )
        candidates = await self._load_classification_candidates(
            owner_user_id=owner_user_id,
            search_results=search_results,
        )
        if not candidates:
            candidates = await self._load_textual_classification_candidates(
                owner_user_id=owner_user_id,
                classification_text=query,
                limit=candidate_limit,
            )
        if not candidates:
            inbox_assignment = await self._create_inbox_assignment(
                owner_user_id=owner_user_id,
                content_object_id=content_object_id,
                dry_run=dry_run,
                confidence=None,
                reasoning="No semantic taxonomy candidates found; assigned to inbox.",
            )
            if inbox_assignment is not None:
                assignment, inbox = inbox_assignment
                selected_category = self._classification_category(inbox)
                return self._classification_response(
                    content_object_id=content_object_id,
                    mode=mode,
                    dry_run=dry_run,
                    assignment=assignment,
                    selected_category=selected_category,
                    status="accepted",
                    confidence=None,
                    reasoning="No semantic taxonomy candidates found; assigned to inbox.",
                    semantic_candidates=[],
                    classification_text=query,
                    llm_decision=None,
                    would_assign=True,
                    would_status="accepted",
                    would_category=selected_category,
                )
            return self._classification_response(
                content_object_id=content_object_id,
                mode=mode,
                dry_run=dry_run,
                assignment=None,
                selected_category=None,
                status="no_assignment",
                confidence=None,
                reasoning="No semantic taxonomy candidates found.",
                semantic_candidates=[],
                classification_text=query,
                llm_decision=None,
                would_assign=False,
                would_status="no_assignment",
                would_category=None,
            )
        if mode == "semantic_only":
            return await self._classify_from_semantic_candidates(
                owner_user_id=owner_user_id,
                content_object_id=content_object_id,
                candidates=candidates,
                classification_text=query,
                dry_run=dry_run,
                response_mode=mode,
                fallback_reason=None,
            )
        return await self._classify_with_llm_judge(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            candidates=candidates,
            classification_text=query,
            dry_run=dry_run,
        )

    async def process_classification_job(self, job: TaxonomyClassificationJob) -> None:
        if job.job_type != "classify_content":
            raise TaxonomyValidationError(f"Unsupported taxonomy job type: {job.job_type}")

        response = await self.classify_content_object_with_response(
            owner_user_id=job.owner_user_id,
            content_object_id=job.content_object_id,
            mode="llm_judge",
            candidate_limit=5,
            dry_run=False,
        )
        assignment = None
        if response.assignment_id is not None:
            assignment = await self.repository.get_assignment(
                owner_user_id=job.owner_user_id,
                content_object_id=job.content_object_id,
                assignment_id=response.assignment_id,
            )

        job.status = "succeeded"
        job.assignment_id = response.assignment_id
        job.result_status = response.status
        job.last_error = None
        job.locked_at = None
        job.locked_by = None
        self._enqueue_classification_completed_event(
            job=job,
            assignment=assignment,
            status=response.status,
            confidence=response.confidence,
        )

    async def mark_classification_failed(
        self,
        job: TaxonomyClassificationJob,
        error: str,
    ) -> None:
        job.last_error = error[:4000]
        job.locked_at = None
        job.locked_by = None
        if job.attempts >= job.max_attempts:
            job.status = "failed"
            return
        job.status = "pending"
        job.run_after = datetime.now(UTC) + timedelta(seconds=min(300, 2**job.attempts))

    async def _classify_from_semantic_candidates(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        candidates: list[ClassificationCandidate],
        classification_text: str,
        dry_run: bool,
        response_mode: Literal["semantic_only", "llm_judge"],
        fallback_reason: str | None,
    ) -> TaxonomyClassificationResponse:
        best = candidates[0]
        if best.result.score < self.settings.taxonomy_classification_medium_threshold:
            reasoning = (
                fallback_reason
                or "Semantic similarity was below assignment threshold; assigned to inbox."
            )
            inbox_assignment = await self._create_inbox_assignment(
                owner_user_id=owner_user_id,
                content_object_id=content_object_id,
                dry_run=dry_run,
                confidence=best.result.score,
                reasoning=reasoning,
            )
            if inbox_assignment is not None:
                assignment, inbox = inbox_assignment
                selected_category = self._classification_category(inbox)
                return self._classification_response(
                    content_object_id=content_object_id,
                    mode=response_mode,
                    dry_run=dry_run,
                    assignment=assignment,
                    selected_category=selected_category,
                    status="accepted",
                    confidence=best.result.score,
                    reasoning=reasoning,
                    semantic_candidates=self._candidate_responses(candidates),
                    classification_text=classification_text,
                    llm_decision=None,
                    would_assign=True,
                    would_status="accepted",
                    would_category=selected_category,
                )
            return self._classification_response(
                content_object_id=content_object_id,
                mode=response_mode,
                dry_run=dry_run,
                assignment=None,
                selected_category=None,
                status="no_assignment",
                confidence=best.result.score,
                reasoning=fallback_reason or "Semantic similarity was below assignment threshold.",
                semantic_candidates=self._candidate_responses(candidates),
                classification_text=classification_text,
                llm_decision=None,
                would_assign=False,
                would_status="no_assignment",
                would_category=None,
            )

        status: Literal["accepted", "proposed"] = (
            "accepted"
            if best.result.score >= self.settings.taxonomy_classification_high_threshold
            else "proposed"
        )
        reasoning = (
            fallback_reason or "Selected by semantic similarity over taxonomy category profiles."
        )
        assignment = None
        if not dry_run:
            assignment = await self._create_current_assignment(
                owner_user_id=owner_user_id,
                content_object_id=content_object_id,
                category=best.category,
                status=status,
                assigned_by="system",
                confidence=best.result.score,
                reasoning=reasoning,
                alternatives=[
                    {
                        "category_id": candidate.category.id,
                        "category_name_snapshot": candidate.category.name,
                        "category_path_snapshot": candidate.category.path,
                        "score": candidate.result.score,
                        "chunk_id": candidate.result.chunk_id,
                    }
                    for candidate in candidates
                ],
                commit=True,
            )
        selected_category = self._classification_category(best.category)
        return self._classification_response(
            content_object_id=content_object_id,
            mode=response_mode,
            dry_run=dry_run,
            assignment=assignment,
            selected_category=selected_category,
            status=status,
            confidence=best.result.score,
            reasoning=reasoning,
            semantic_candidates=self._candidate_responses(candidates),
            classification_text=classification_text,
            llm_decision=None,
            would_assign=True,
            would_status=status,
            would_category=selected_category,
        )

    def _enqueue_classification_completed_event(
        self,
        *,
        job: TaxonomyClassificationJob,
        assignment: TaxonomyContentAssignment | None,
        status: Literal["accepted", "proposed", "no_assignment"],
        confidence: float | None,
    ) -> None:
        envelope = EventEnvelope.new(
            event_name="taxonomy.classification.completed",
            entity_id=job.content_object_id,
            correlation_id=job.correlation_id or str(uuid4()),
            user_id=job.owner_user_id,
            payload=TaxonomyClassificationCompletedPayload(
                content_object_id=job.content_object_id,
                assignment_id=assignment.id if assignment is not None else None,
                status=status,
                assigned_by=(
                    cast(Literal["system", "llm"], assignment.assigned_by)
                    if assignment is not None and assignment.assigned_by in {"system", "llm"}
                    else None
                ),
                confidence=confidence,
            ),
        )
        self.outbox.add(envelope, routing_key="taxonomy.classification.completed")

    async def _classify_with_llm_judge(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        candidates: list[ClassificationCandidate],
        classification_text: str,
        dry_run: bool,
    ) -> TaxonomyClassificationResponse:
        try:
            llm_decision = await self._run_llm_judge(
                classification_text=classification_text,
                candidates=candidates,
            )
            selected_category_id = llm_decision.selected_category_id
            candidate_by_id = {candidate.category.id: candidate for candidate in candidates}
            if llm_decision.should_assign and llm_decision.status != "no_assignment":
                if selected_category_id not in candidate_by_id:
                    raise TaxonomyLLMClassificationError(
                        "LLM selected a category outside semantic candidates."
                    )
                selected = candidate_by_id[str(selected_category_id)]
            else:
                selected = None
        except (LLMGenerationError, TaxonomyLLMClassificationError, ValidationError) as exc:
            if not self.settings.taxonomy_llm_classification_fallback_to_semantic:
                if isinstance(exc, TaxonomyLLMClassificationError):
                    raise
                raise TaxonomyLLMClassificationError(str(exc)) from exc
            return await self._classify_from_semantic_candidates(
                owner_user_id=owner_user_id,
                content_object_id=content_object_id,
                candidates=candidates,
                classification_text=classification_text,
                dry_run=dry_run,
                response_mode="llm_judge",
                fallback_reason=(
                    "LLM judge failed; fell back to semantic-only classification: " f"{exc}"
                ),
            )

        if selected is None or llm_decision.confidence < (
            self.settings.taxonomy_llm_classification_propose_threshold
        ):
            return self._classification_response(
                content_object_id=content_object_id,
                mode="llm_judge",
                dry_run=dry_run,
                assignment=None,
                selected_category=None,
                status="no_assignment",
                confidence=llm_decision.confidence,
                reasoning=llm_decision.reasoning,
                semantic_candidates=self._candidate_responses(candidates),
                classification_text=classification_text,
                llm_decision=llm_decision,
                would_assign=False,
                would_status="no_assignment",
                would_category=None,
            )

        status: Literal["accepted", "proposed"] = (
            "accepted"
            if llm_decision.confidence >= self.settings.taxonomy_llm_classification_accept_threshold
            else "proposed"
        )
        assignment = None
        if not dry_run:
            assignment = await self._create_current_assignment(
                owner_user_id=owner_user_id,
                content_object_id=content_object_id,
                category=selected.category,
                status=status,
                assigned_by="llm",
                confidence=llm_decision.confidence,
                reasoning=llm_decision.reasoning,
                alternatives=self._llm_assignment_audit(
                    candidates=candidates,
                    llm_decision=llm_decision,
                ),
                commit=True,
            )
        selected_category = self._classification_category(selected.category)
        return self._classification_response(
            content_object_id=content_object_id,
            mode="llm_judge",
            dry_run=dry_run,
            assignment=assignment,
            selected_category=selected_category,
            status=status,
            confidence=llm_decision.confidence,
            reasoning=llm_decision.reasoning,
            semantic_candidates=self._candidate_responses(candidates),
            classification_text=classification_text,
            llm_decision=llm_decision,
            would_assign=True,
            would_status=status,
            would_category=selected_category,
        )

    async def _create_inbox_assignment(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        dry_run: bool,
        confidence: float | None,
        reasoning: str,
    ) -> tuple[TaxonomyContentAssignment, TaxonomyCategory] | None:
        inbox = await self.repository.get_category_by_path(
            owner_user_id=owner_user_id,
            path="inbox",
            include_archived=False,
        )
        if inbox is None:
            return None
        if dry_run:
            assignment = TaxonomyContentAssignment(
                owner_user_id=owner_user_id,
                content_object_id=content_object_id,
                category_id=inbox.id,
                category_name_snapshot=inbox.name,
                category_path_snapshot=inbox.path,
                status="accepted",
                confidence=confidence,
                reasoning=reasoning,
                assigned_by="system",
                alternatives=[],
                is_current=False,
            )
            return assignment, inbox
        assignment = await self._create_current_assignment(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            category=inbox,
            status="accepted",
            assigned_by="system",
            confidence=confidence,
            reasoning=reasoning,
            alternatives=[],
            commit=True,
        )
        return assignment, inbox

    async def _run_llm_judge(
        self,
        *,
        classification_text: str,
        candidates: list[ClassificationCandidate],
    ) -> TaxonomyLLMDecisionResponse:
        result = await self.llm_generator.generate_structured(
            prompt=self._build_llm_judge_prompt(
                classification_text=classification_text,
                candidates=candidates,
            ),
            schema=self._llm_judge_schema(),
            model_config={
                "model": self.settings.taxonomy_llm_classification_model,
                "temperature": 0,
                "max_tokens": 768,
            },
        )
        decision = TaxonomyLLMDecisionResponse.model_validate(result)
        candidate_ids = {candidate.category.id for candidate in candidates}
        if decision.selected_category_id is not None and (
            decision.selected_category_id not in candidate_ids
        ):
            raise TaxonomyLLMClassificationError(
                "LLM selected a category outside semantic candidates."
            )
        for alternative in decision.alternatives:
            category_id = alternative.get("category_id")
            if category_id is not None and category_id not in candidate_ids:
                raise TaxonomyLLMClassificationError(
                    "LLM returned an alternative outside semantic candidates."
                )
        return decision

    async def _load_classification_candidates(
        self,
        *,
        owner_user_id: str,
        search_results: list[SemanticSearchResult],
    ) -> list[ClassificationCandidate]:
        candidates: list[ClassificationCandidate] = []
        seen_category_ids: set[str] = set()
        for result in search_results:
            if result.source != "taxonomy" or result.source_type != "category_profile":
                continue
            if result.source_id in seen_category_ids:
                continue
            category = await self.repository.get_category(
                owner_user_id=owner_user_id,
                category_id=result.source_id,
                include_archived=False,
            )
            if category is None:
                continue
            profile = await self.repository.get_profile(category_id=category.id)
            candidates.append(
                ClassificationCandidate(result=result, category=category, profile=profile)
            )
            seen_category_ids.add(category.id)
        return candidates

    async def _load_textual_classification_candidates(
        self,
        *,
        owner_user_id: str,
        classification_text: str,
        limit: int,
    ) -> list[ClassificationCandidate]:
        query_tokens = self._classification_tokens(classification_text)
        if not query_tokens:
            return []
        categories = await self.repository.list_categories_with_profiles(
            owner_user_id=owner_user_id,
            include_archived=False,
        )
        scored: list[tuple[float, TaxonomyCategory, TaxonomyCategoryProfile | None, str]] = []
        for category in categories:
            profile = category.profile
            document = self._category_textual_candidate_document(category, profile)
            document_tokens = self._classification_tokens(document)
            if not document_tokens:
                continue
            matches = query_tokens & document_tokens
            if not matches:
                continue
            keyword_matches = set()
            if profile is not None:
                keyword_matches = query_tokens & self._classification_tokens(
                    " ".join(profile.keywords)
                )
            score = min(
                0.95,
                0.52
                + (len(matches) * 0.045)
                + (len(keyword_matches) * 0.06)
                + (category.depth * 0.015),
            )
            scored.append((score, category, profile, document))

        scored.sort(key=lambda item: (item[0], item[1].depth, -item[1].sort_order), reverse=True)
        candidates: list[ClassificationCandidate] = []
        for score, category, profile, document in scored[:limit]:
            candidates.append(
                ClassificationCandidate(
                    result=SemanticSearchResult(
                        source="taxonomy",
                        source_type="category_profile",
                        source_id=category.id,
                        external_id=f"taxonomy_category_profile:{category.id}",
                        chunk_id=f"textual:{category.id}",
                        chunk_external_id=f"taxonomy_category_profile:{category.id}:textual",
                        text=document,
                        metadata={
                            "category_path": category.path,
                            "candidate_source": "textual_profile_fallback",
                        },
                        distance=1 - score,
                        score=score,
                    ),
                    category=category,
                    profile=profile,
                )
            )
        return candidates

    @staticmethod
    def _category_textual_candidate_document(
        category: TaxonomyCategory,
        profile: TaxonomyCategoryProfile | None,
    ) -> str:
        parts = [
            category.path.replace("/", " "),
            category.name,
            category.description or "",
        ]
        if profile is not None:
            parts.extend(
                [
                    profile.summary or "",
                    " ".join(profile.keywords),
                    " ".join(profile.positive_examples),
                    " ".join(profile.negative_examples),
                ]
            )
        return "\n".join(part for part in parts if part)

    @staticmethod
    def _classification_tokens(text: str) -> set[str]:
        return {
            token.casefold()
            for token in re.findall(r"[0-9A-Za-zА-Яа-яЁё]{2,}", text)
            if token.casefold()
            not in {
                "type",
                "content",
                "object",
                "title",
                "tags",
                "url",
                "and",
                "the",
                "для",
                "про",
                "или",
                "это",
            }
        }

    def _build_llm_judge_prompt(
        self,
        *,
        classification_text: str,
        candidates: list[ClassificationCandidate],
    ) -> str:
        lines = [
            f"prompt_version = {LLM_JUDGE_PROMPT_VERSION}",
            "",
            "You are a taxonomy classification judge.",
            "Choose only from provided candidates.",
            "Do not create categories, rename categories, move categories, "
            "or choose a category outside the candidate list.",
            "Prefer the deepest specific category when it clearly fits.",
            "Prefer a parent or broader category only if the specific candidate is too narrow.",
            "Return should_assign = false if none of the candidates fit.",
            "Use semantic score as a signal, not as the only decision factor.",
            "Explain briefly why the selected category fits.",
            "",
            "Content:",
            classification_text,
            "",
            "Candidates:",
        ]
        for candidate in candidates:
            profile = candidate.profile
            profile_summary = profile.summary if profile is not None and profile.summary else ""
            lines.extend(
                [
                    f"- candidate_id: {candidate.category.id}",
                    f"  path: {candidate.category.path}",
                    f"  name: {candidate.category.name}",
                    f"  description: {candidate.category.description or ''}",
                    f"  profile_summary: {profile_summary}",
                    "  keywords: "
                    + (
                        ", ".join(profile.keywords)
                        if profile is not None and profile.keywords
                        else ""
                    ),
                    "  positive_examples: "
                    + (
                        "; ".join(profile.positive_examples)
                        if profile is not None and profile.positive_examples
                        else ""
                    ),
                    "  negative_examples: "
                    + (
                        "; ".join(profile.negative_examples)
                        if profile is not None and profile.negative_examples
                        else ""
                    ),
                    f"  semantic_score: {candidate.result.score:.6f}",
                ]
            )
        return "\n".join(lines)

    def _build_profile_improvement_prompt(
        self,
        *,
        category: TaxonomyCategory,
        profile: TaxonomyCategoryProfile | None,
        children: list[TaxonomyCategory],
        user_guidance: str,
    ) -> str:
        return "\n".join(
            [
                "prompt_version = taxonomy_profile_improvement_v1",
                "",
                "You improve taxonomy category profiles for a personal knowledge base.",
                "Return a draft only. Do not save or apply changes.",
                "Keep the category boundary practical for classification.",
                "Prefer concise Russian text if the user guidance is in Russian.",
                "",
                "Category:",
                f"Path: {category.path}",
                f"Name: {category.name}",
                f"Description: {category.description or ''}",
                "",
                "Current profile:",
                f"Summary: {profile.summary if profile is not None and profile.summary else ''}",
                "Keywords: "
                + (", ".join(profile.keywords) if profile is not None and profile.keywords else ""),
                "Positive examples: "
                + (
                    " | ".join(profile.positive_examples)
                    if profile is not None and profile.positive_examples
                    else ""
                ),
                "Negative examples: "
                + (
                    " | ".join(profile.negative_examples)
                    if profile is not None and profile.negative_examples
                    else ""
                ),
                "",
                "Child categories:",
                *[f"- {child.path}: {child.description or child.name}" for child in children],
                "",
                "User guidance:",
                user_guidance,
                "",
                "Interpret this as an AI infrastructure taxonomy request when relevant.",
            ]
        )

    @staticmethod
    def _llm_judge_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "required": [
                "selected_category_id",
                "confidence",
                "should_assign",
                "status",
                "reasoning",
                "alternatives",
            ],
            "properties": {
                "selected_category_id": {"type": ["string", "null"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "should_assign": {"type": "boolean"},
                "status": {"enum": ["accepted", "proposed", "no_assignment"]},
                "reasoning": {"type": "string"},
                "alternatives": {"type": "array"},
            },
        }

    async def list_templates(self) -> list[TaxonomyTemplate]:
        await self._ensure_templates_seeded()
        return await self.repository.list_templates()

    def list_interest_options(self) -> list[InterestOption]:
        return [
            InterestOption(
                slug=slug,
                name=str(config["name"]),
                description=str(config["description"]),
            )
            for slug, config in self._interest_presets().items()
        ]

    async def get_template(self, *, template_slug: str) -> TaxonomyTemplate:
        await self._ensure_templates_seeded()
        template = await self.repository.get_template_by_slug(slug=template_slug)
        if template is None:
            raise TaxonomyNotFoundError
        return template

    async def initialize_from_template(
        self,
        *,
        owner_user_id: str,
        template_slug: str,
    ) -> InitializeTaxonomyResult:
        if await self.repository.has_categories(owner_user_id=owner_user_id):
            raise TaxonomyConflictError
        template = await self.get_template(template_slug=template_slug)
        template_categories = await self.repository.list_template_categories(
            template_id=template.id,
        )

        created_by_template_id: dict[str, TaxonomyCategory] = {}
        created_profiles = 0
        for template_category in template_categories:
            parent = (
                created_by_template_id[template_category.parent_id]
                if template_category.parent_id is not None
                else None
            )
            category = TaxonomyCategory(
                owner_user_id=owner_user_id,
                parent_id=parent.id if parent is not None else None,
                slug=template_category.slug,
                name=template_category.name,
                description=template_category.description,
                path=template_category.path,
                depth=template_category.depth,
                sort_order=template_category.sort_order,
                source="system" if template_category.path == "inbox" else "template",
                is_system=template_category.path == "inbox",
            )
            self.repository.add_category(category)
            await self.session.flush()
            created_by_template_id[template_category.id] = category
            profile = TaxonomyCategoryProfile(
                category_id=category.id,
                summary=template_category.profile_summary,
                keywords=template_category.profile_keywords,
                positive_examples=template_category.profile_positive_examples,
                negative_examples=template_category.profile_negative_examples,
            )
            self.repository.add_profile(profile)
            await self._enqueue_category_profile_index(
                owner_user_id=owner_user_id,
                category_id=category.id,
                priority=100,
            )
            created_profiles += 1

        if not any(category.path == "inbox" for category in created_by_template_id.values()):
            inbox = TaxonomyCategory(
                owner_user_id=owner_user_id,
                slug="inbox",
                name="Inbox",
                description="Default category for uncategorized content.",
                path="inbox",
                depth=0,
                sort_order=0,
                source="system",
                is_system=True,
            )
            self.repository.add_category(inbox)
            await self.session.flush()
            self.repository.add_profile(
                TaxonomyCategoryProfile(
                    category_id=inbox.id,
                    summary="Default category for uncategorized content.",
                    keywords=["inbox", "uncategorized"],
                    positive_examples=["new item without a clear category"],
                    negative_examples=["well-classified project material"],
                )
            )
            await self._enqueue_category_profile_index(
                owner_user_id=owner_user_id,
                category_id=inbox.id,
                priority=100,
            )
            created_profiles += 1
        await self.session.commit()
        return InitializeTaxonomyResult(
            owner_user_id=owner_user_id,
            template_slug=template.slug,
            created_categories_count=len(created_by_template_id),
            created_profiles_count=created_profiles,
        )

    async def initialize_from_interests(
        self,
        *,
        owner_user_id: str,
        interest_slugs: list[str],
        custom_description: str | None,
    ) -> InitializeTaxonomyResult:
        if await self.repository.has_categories(owner_user_id=owner_user_id):
            raise TaxonomyConflictError

        selected_slugs = list(
            dict.fromkeys(slug.strip() for slug in interest_slugs if slug.strip())
        )
        custom_description = custom_description.strip() if custom_description else None
        if not selected_slugs and not custom_description:
            raise TaxonomyValidationError

        presets = self._interest_presets()
        unknown = [slug for slug in selected_slugs if slug not in presets]
        if unknown:
            raise TaxonomyValidationError

        tree = [self._node("Inbox")]
        for slug in selected_slugs:
            tree.extend(cast(list[dict[str, object]], presets[slug]["tree"]))
        if custom_description:
            tree.extend(await self._custom_interest_tree(custom_description))

        created_by_path: dict[str, TaxonomyCategory] = {}
        created_profiles = 0
        for item in self._flatten_template_tree(tree):
            path = str(item["path"])
            if path in created_by_path:
                continue
            parent_path = path.rsplit("/", 1)[0] if "/" in path else None
            parent = created_by_path.get(parent_path) if parent_path is not None else None
            category = TaxonomyCategory(
                owner_user_id=owner_user_id,
                parent_id=parent.id if parent is not None else None,
                slug=str(item["slug"]),
                name=str(item["name"]),
                description=str(item["description"]),
                path=path,
                depth=cast(int, item["depth"]),
                sort_order=cast(int, item["sort_order"]),
                source="system" if path == "inbox" else "onboarding",
                is_system=path == "inbox",
            )
            self.repository.add_category(category)
            await self.session.flush()
            created_by_path[path] = category
            self.repository.add_profile(
                TaxonomyCategoryProfile(
                    category_id=category.id,
                    summary=str(item["profile_summary"]),
                    keywords=cast(list[str], item["profile_keywords"]),
                    positive_examples=cast(list[str], item["profile_positive_examples"]),
                    negative_examples=cast(list[str], item["profile_negative_examples"]),
                )
            )
            await self._enqueue_category_profile_index(
                owner_user_id=owner_user_id,
                category_id=category.id,
                priority=100,
            )
            created_profiles += 1

        await self.session.commit()
        return InitializeTaxonomyResult(
            owner_user_id=owner_user_id,
            template_slug="interests",
            created_categories_count=len(created_by_path),
            created_profiles_count=created_profiles,
        )

    async def _create_current_assignment(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        category: TaxonomyCategory,
        status: str,
        assigned_by: str,
        confidence: float | None,
        reasoning: str | None,
        alternatives: list[dict[str, object]] | None = None,
        commit: bool,
    ) -> TaxonomyContentAssignment:
        await self.repository.override_current_assignments(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
        )
        assignment = TaxonomyContentAssignment(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            category_id=category.id,
            status=status,
            confidence=confidence,
            reasoning=reasoning,
            assigned_by=assigned_by,
            alternatives=alternatives or [],
            category_name_snapshot=category.name,
            category_path_snapshot=category.path,
            is_current=True,
        )
        assignment.category = category
        self.repository.add_assignment(assignment)
        await self.session.flush()
        if commit:
            await self.session.commit()
            await self.session.refresh(assignment)
        return assignment

    async def _classification_alternatives(
        self,
        *,
        owner_user_id: str,
        candidates: list[SemanticSearchResult],
    ) -> list[dict[str, object]]:
        alternatives: list[dict[str, object]] = []
        for candidate in candidates:
            category = await self.repository.get_category(
                owner_user_id=owner_user_id,
                category_id=candidate.source_id,
                include_archived=False,
            )
            if category is None:
                continue
            alternatives.append(
                {
                    "category_id": category.id,
                    "category_name_snapshot": category.name,
                    "category_path_snapshot": category.path,
                    "score": candidate.score,
                    "chunk_id": candidate.chunk_id,
                }
            )
        return alternatives

    def _llm_assignment_audit(
        self,
        *,
        candidates: list[ClassificationCandidate],
        llm_decision: TaxonomyLLMDecisionResponse,
    ) -> list[dict[str, object]]:
        return [
            {
                "classification_mode": "llm_judge",
                "prompt_version": LLM_JUDGE_PROMPT_VERSION,
                "llm_model": self.settings.taxonomy_llm_classification_model,
                "semantic_candidates": [
                    {
                        "category_id": candidate.category.id,
                        "category_path": candidate.category.path,
                        "score": candidate.result.score,
                        "chunk_id": candidate.result.chunk_id,
                    }
                    for candidate in candidates
                ],
                "llm_decision": {
                    "selected_category_id": llm_decision.selected_category_id,
                    "confidence": llm_decision.confidence,
                    "reasoning": llm_decision.reasoning,
                    "status": llm_decision.status,
                    "should_assign": llm_decision.should_assign,
                },
            },
            *llm_decision.alternatives,
        ]

    @staticmethod
    def _classification_category(
        category: TaxonomyCategory,
    ) -> TaxonomyClassificationCategoryResponse:
        return TaxonomyClassificationCategoryResponse(
            id=category.id,
            name=category.name,
            path=category.path,
        )

    @staticmethod
    def _candidate_responses(
        candidates: list[ClassificationCandidate],
    ) -> list[TaxonomyClassificationCandidateResponse]:
        return [
            TaxonomyClassificationCandidateResponse(
                category_id=candidate.category.id,
                category_name=candidate.category.name,
                category_path=candidate.category.path,
                score=candidate.result.score,
                chunk_id=candidate.result.chunk_id,
            )
            for candidate in candidates
        ]

    @staticmethod
    def _classification_response(
        *,
        content_object_id: str,
        mode: Literal["semantic_only", "llm_judge"],
        dry_run: bool,
        assignment: TaxonomyContentAssignment | None,
        selected_category: TaxonomyClassificationCategoryResponse | None,
        status: Literal["accepted", "proposed", "no_assignment"],
        confidence: float | None,
        reasoning: str | None,
        semantic_candidates: list[TaxonomyClassificationCandidateResponse],
        classification_text: str,
        llm_decision: TaxonomyLLMDecisionResponse | None,
        would_assign: bool,
        would_status: Literal["accepted", "proposed", "no_assignment"],
        would_category: TaxonomyClassificationCategoryResponse | None,
    ) -> TaxonomyClassificationResponse:
        return TaxonomyClassificationResponse(
            content_object_id=content_object_id,
            mode=mode,
            dry_run=dry_run,
            assigned=assignment is not None,
            assignment_id=assignment.id if assignment is not None else None,
            selected_category=selected_category,
            status=status,
            confidence=confidence,
            reasoning=reasoning,
            semantic_candidates=semantic_candidates,
            classification_text_preview=classification_text[:1000],
            llm_decision=llm_decision,
            would_assign=would_assign,
            would_status=would_status,
            would_category=would_category,
        )

    @staticmethod
    def _build_classification_query(
        *,
        title: str,
        url: str | None,
        tags: list[str],
        text_excerpt: str | None,
    ) -> str:
        lines = [
            "Type: content_object",
            f"Title: {title}",
            f"URL: {url or ''}",
            f"Tags: {', '.join(tags)}",
            "Content:",
        ]
        if text_excerpt:
            lines.append(text_excerpt)
        return "\n".join(lines).strip()

    async def _ensure_unique_category(
        self,
        *,
        owner_user_id: str,
        parent_id: str | None,
        slug: str,
        path: str,
        except_category_id: str | None = None,
    ) -> None:
        if await self.repository.category_slug_exists(
            owner_user_id=owner_user_id,
            parent_id=parent_id,
            slug=slug,
            except_category_id=except_category_id,
        ):
            raise TaxonomyConflictError
        if await self.repository.category_path_exists(
            owner_user_id=owner_user_id,
            path=path,
            except_category_id=except_category_id,
        ):
            raise TaxonomyConflictError

    async def _ensure_content_exists(self, owner_user_id: str, content_object_id: str) -> None:
        content_object = await self.repository.get_content_object(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
        )
        if content_object is None:
            raise TaxonomyNotFoundError

    async def _enqueue_category_profile_index(
        self,
        *,
        owner_user_id: str,
        category_id: str,
        priority: int,
    ) -> None:
        existing = await self.session.scalar(
            select(VectorizationJob.id).where(
                VectorizationJob.owner_user_id == owner_user_id,
                VectorizationJob.source == "taxonomy",
                VectorizationJob.source_type == "category_profile",
                VectorizationJob.source_id == category_id,
                VectorizationJob.status.in_(("pending", "processing")),
            )
        )
        if existing is not None:
            return
        self.session.add(
            VectorizationJob(
                owner_user_id=owner_user_id,
                job_type="index_source",
                source="taxonomy",
                source_type="category_profile",
                source_id=category_id,
                status="pending",
                priority=priority,
            )
        )

    async def _load_assignment(
        self,
        owner_user_id: str,
        content_object_id: str,
        assignment_id: str,
    ) -> TaxonomyContentAssignment:
        await self._ensure_content_exists(owner_user_id, content_object_id)
        assignment = await self.repository.get_assignment(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            assignment_id=assignment_id,
        )
        if assignment is None:
            raise TaxonomyNotFoundError
        return assignment

    @staticmethod
    def category_response(category: TaxonomyCategory) -> TaxonomyCategoryResponse:
        return TaxonomyCategoryResponse.model_validate(category, from_attributes=True)

    @staticmethod
    def profile_response(profile: TaxonomyCategoryProfile) -> TaxonomyProfileResponse:
        return TaxonomyProfileResponse.model_validate(profile, from_attributes=True)

    @staticmethod
    def settings_response(settings: TaxonomyUserSettings) -> TaxonomySettingsResponse:
        return TaxonomySettingsResponse.model_validate(settings, from_attributes=True)

    @staticmethod
    def assignment_response(assignment: TaxonomyContentAssignment) -> TaxonomyAssignmentResponse:
        return TaxonomyAssignmentResponse(
            id=assignment.id,
            content_object_id=assignment.content_object_id,
            category_id=assignment.category_id,
            category_path=assignment.category_path_snapshot,
            category_name_snapshot=assignment.category_name_snapshot,
            category_path_snapshot=assignment.category_path_snapshot,
            status=assignment.status,  # type: ignore[arg-type]
            confidence=float(assignment.confidence) if assignment.confidence is not None else None,
            reasoning=assignment.reasoning,
            assigned_by=assignment.assigned_by,  # type: ignore[arg-type]
            alternatives=assignment.alternatives,
            is_current=assignment.is_current,
            created_at=assignment.created_at,
            updated_at=assignment.updated_at,
        )

    @staticmethod
    def template_summary(template: TaxonomyTemplate) -> TaxonomyTemplateSummaryResponse:
        return TaxonomyTemplateSummaryResponse.model_validate(template, from_attributes=True)

    @staticmethod
    def template_detail(
        template: TaxonomyTemplate,
        categories: list[TaxonomyTemplateCategory],
    ) -> TaxonomyTemplateDetailResponse:
        by_parent: dict[str | None, list[TaxonomyTemplateCategory]] = {}
        for category in categories:
            by_parent.setdefault(category.parent_id, []).append(category)
        for children in by_parent.values():
            children.sort(key=lambda item: (item.sort_order, item.name.casefold()))

        def build(category: TaxonomyTemplateCategory) -> TaxonomyTemplateTreeItem:
            return TaxonomyTemplateTreeItem(
                id=category.id,
                slug=category.slug,
                name=category.name,
                description=category.description,
                path=category.path,
                depth=category.depth,
                sort_order=category.sort_order,
                profile_summary=category.profile_summary,
                profile_keywords=category.profile_keywords,
                profile_positive_examples=category.profile_positive_examples,
                profile_negative_examples=category.profile_negative_examples,
                children=[build(child) for child in by_parent.get(category.id, [])],
            )

        return TaxonomyTemplateDetailResponse(
            id=template.id,
            slug=template.slug,
            name=template.name,
            description=template.description,
            is_active=template.is_active,
            tree=[build(category) for category in by_parent.get(None, [])],
        )

    async def _ensure_templates_seeded(self) -> None:
        if await self.repository.has_templates():
            return
        for slug, name, tree in (
            ("default", "Default", self._default_template_tree()),
            ("developer", "Developer", self._developer_template_tree()),
        ):
            template = TaxonomyTemplate(
                slug=slug,
                name=name,
                description=f"{name} cold-start taxonomy template.",
                is_active=True,
            )
            self.repository.add_template(template)
            await self.session.flush()
            by_path: dict[str, TaxonomyTemplateCategory] = {}
            for item in self._flatten_template_tree(tree):
                path = str(item["path"])
                parent_path = path.rsplit("/", 1)[0] if "/" in path else None
                category = TaxonomyTemplateCategory(
                    template_id=template.id,
                    parent_id=by_path[parent_path].id if parent_path else None,
                    slug=str(item["slug"]),
                    name=str(item["name"]),
                    description=str(item["description"]),
                    path=path,
                    depth=cast(int, item["depth"]),
                    sort_order=cast(int, item["sort_order"]),
                    profile_summary=str(item["profile_summary"]),
                    profile_keywords=cast(list[str], item["profile_keywords"]),
                    profile_positive_examples=cast(
                        list[str],
                        item["profile_positive_examples"],
                    ),
                    profile_negative_examples=cast(
                        list[str],
                        item["profile_negative_examples"],
                    ),
                )
                self.session.add(category)
                await self.session.flush()
                by_path[category.path] = category
        await self.session.commit()

    @staticmethod
    def _validate_slug(slug: str) -> str:
        value = slug.strip()
        if not value or not SLUG_PATTERN.fullmatch(value):
            raise TaxonomyValidationError
        return value

    @staticmethod
    def _validate_name(name: str) -> str:
        value = name.strip()
        if not value:
            raise TaxonomyValidationError
        return value

    @staticmethod
    def _slugify_path_segment(value: str) -> str:
        slug = re.sub(r"[^a-z0-9_-]+", "-", value.strip().lower()).strip("-")
        if not slug:
            raise TaxonomyValidationError
        return slug

    @staticmethod
    def _profile(name: str) -> dict[str, object]:
        keyword = TaxonomyService._slugify_path_segment(name)
        return {
            "profile_summary": f"Materials related to {name}.",
            "profile_keywords": [keyword],
            "profile_positive_examples": [f"example item about {name}"],
            "profile_negative_examples": [f"item unrelated to {name}"],
        }

    @staticmethod
    def _node(
        name: str,
        children: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        return {"name": name, "children": children or []}

    @classmethod
    def _flatten_template_tree(
        cls,
        tree: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        flattened: list[dict[str, object]] = []

        def visit(nodes: list[dict[str, object]], parent_path: str, depth: int) -> None:
            for index, node in enumerate(nodes):
                name = str(node["name"])
                slug = cls._slugify_path_segment(name)
                path = f"{parent_path}/{slug}".strip("/")
                flattened.append(
                    {
                        "slug": slug,
                        "name": name,
                        "description": str(
                            node.get("description") or f"Materials related to {name}."
                        ),
                        "path": path,
                        "depth": depth,
                        "sort_order": index * 10,
                        **cls._profile(name),
                    }
                )
                visit(node["children"], path, depth + 1)  # type: ignore[arg-type]

        visit(tree, "", 0)
        return flattened

    async def _custom_interest_tree(self, custom_description: str) -> list[dict[str, object]]:
        try:
            result = await self.llm_generator.generate_structured(
                prompt=self._build_custom_interest_prompt(custom_description),
                schema=self._custom_interest_schema(),
                model_config={
                    "model": self.settings.taxonomy_llm_classification_model,
                    "temperature": 0.2,
                    "max_tokens": 900,
                },
            )
            raw_nodes = result.get("categories")
            if not isinstance(raw_nodes, list):
                raise TaxonomyValidationError
            nodes = [
                self._generated_node_to_template_node(_GeneratedInterestNode.model_validate(node))
                for node in raw_nodes[:6]
            ]
            if nodes:
                return nodes
        except (LLMGenerationError, TaxonomyValidationError, ValidationError):
            pass
        return [
            self._node(
                "Custom Interests",
                [
                    self._node("Research"),
                    self._node("Projects"),
                    self._node("Learning"),
                ],
            )
            | {
                "description": f"User-described interests: {custom_description[:500]}",
            }
        ]

    @staticmethod
    def _generated_node_to_template_node(node: _GeneratedInterestNode) -> dict[str, object]:
        return {
            "name": node.name,
            "children": [
                TaxonomyService._generated_node_to_template_node(child)
                for child in node.children[:8]
            ],
        }

    @staticmethod
    def _build_custom_interest_prompt(custom_description: str) -> str:
        return (
            "Create a concise personal knowledge taxonomy from the user's interests. "
            "Return 3-6 top-level categories, with up to 4 useful children each. "
            "Use short category names. Do not include generic labels like Misc or Other. "
            "Return JSON only.\n\n"
            f"User interests:\n{custom_description[:2000]}"
        )

    @staticmethod
    def _custom_interest_schema() -> dict[str, Any]:
        child_schema: dict[str, Any] = {
            "type": "object",
            "required": ["name", "children"],
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 80},
                "children": {"type": "array", "maxItems": 0},
            },
        }
        node_schema: dict[str, Any] = {
            "type": "object",
            "required": ["name", "children"],
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 80},
                "children": {"type": "array", "maxItems": 8, "items": child_schema},
            },
        }
        return {
            "type": "object",
            "required": ["categories"],
            "properties": {
                "categories": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 6,
                    "items": node_schema,
                }
            },
        }

    @classmethod
    def _interest_presets(cls) -> dict[str, dict[str, object]]:
        node = cls._node
        return {
            "software": {
                "name": "Programming",
                "description": "Backend, frontend, languages, databases, and architecture.",
                "tree": [
                    node(
                        "Programming",
                        [
                            node("Python"),
                            node("JavaScript"),
                            node("Backend"),
                            node("Frontend"),
                            node("Databases"),
                            node("Architecture"),
                        ],
                    )
                ],
            },
            "ai": {
                "name": "AI",
                "description": "LLMs, agents, RAG, machine learning, and AI tools.",
                "tree": [
                    node(
                        "AI",
                        [
                            node("LLM"),
                            node("Agents"),
                            node("RAG"),
                            node("Machine Learning"),
                            node("Tools"),
                        ],
                    )
                ],
            },
            "design": {
                "name": "Design",
                "description": "UX, interfaces, visual references, and product design.",
                "tree": [
                    node("Design", [node("UX"), node("UI"), node("Research"), node("References")])
                ],
            },
            "business": {
                "name": "Business",
                "description": "Product, strategy, marketing, sales, and operations.",
                "tree": [
                    node(
                        "Business",
                        [node("Product"), node("Strategy"), node("Marketing"), node("Sales")],
                    )
                ],
            },
            "science": {
                "name": "Science",
                "description": "Research papers, experiments, data, and technical domains.",
                "tree": [
                    node(
                        "Science",
                        [node("Papers"), node("Experiments"), node("Data"), node("Notes")],
                    )
                ],
            },
            "life": {
                "name": "Personal",
                "description": "Learning, health, finance, travel, ideas, and personal notes.",
                "tree": [
                    node(
                        "Personal",
                        [node("Learning"), node("Health"), node("Finance"), node("Ideas")],
                    )
                ],
            },
        }

    @classmethod
    def _default_template_tree(cls) -> list[dict[str, object]]:
        node = cls._node
        return [
            node("Inbox"),
            node("AI", [node("LLM"), node("Agents"), node("Machine Learning"), node("Tools")]),
            node(
                "Programming",
                [
                    node("Python"),
                    node("JavaScript"),
                    node("Backend"),
                    node("Frontend"),
                    node("Databases"),
                    node("Architecture"),
                ],
            ),
            node("Data", [node("Analytics"), node("Data Engineering"), node("Visualization")]),
            node(
                "Business",
                [node("Product"), node("Marketing"), node("Sales"), node("Strategy")],
            ),
            node("Resources", [node("Articles"), node("Books"), node("Videos"), node("Tools")]),
            node("Personal", [node("Ideas"), node("Tasks"), node("Learning"), node("Notes")]),
        ]

    @classmethod
    def _developer_template_tree(cls) -> list[dict[str, object]]:
        node = cls._node
        return [
            node("Inbox"),
            node("AI", [node("LLM"), node("Agents"), node("RAG"), node("Tools")]),
            node(
                "Programming",
                [
                    node("Python"),
                    node("JavaScript"),
                    node("Backend"),
                    node("APIs"),
                    node("Architecture"),
                    node("Testing"),
                ],
            ),
            node("Databases", [node("PostgreSQL"), node("Redis"), node("Vector Search")]),
            node("DevOps", [node("Docker"), node("CI/CD"), node("Observability")]),
            node("Product", [node("Ideas"), node("UX"), node("Strategy")]),
            node("Resources", [node("Articles"), node("Videos"), node("Tools")]),
        ]
