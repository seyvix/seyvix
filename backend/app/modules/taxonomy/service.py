"""User-facing taxonomy operations: categories, profiles, settings, assignments, jobs.

Classification lives in `classification.py`, onboarding in `onboarding.py`, prompts in
`prompts.py`. Construction is cheap (no clients, no I/O) — other modules may build a
`TaxonomyService` per request.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.modules.content.sync import touch_content_objects
from app.modules.llm.client import AIClient
from app.modules.tags.infrastructure.repositories import upsert_content_jobs
from app.modules.taxonomy.classification import category_info, create_current_assignment
from app.modules.taxonomy.contracts import AutomaticApplyMode, TaxonomyAssignmentStatus
from app.modules.taxonomy.errors import (
    TaxonomyConflictError,
    TaxonomyNotFoundError,
    TaxonomyPermissionError,
    TaxonomyValidationError,
)
from app.modules.taxonomy.infrastructure.repositories import TaxonomyRepository
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
from app.modules.taxonomy.onboarding import (
    CATEGORY_SLUG_RE,
    InitializeTaxonomyResult,
    build_interest_tree,
    category_slug,
    create_categories_from_tree,
    custom_interest_tree,
    profile_for_new_category,
)
from app.modules.taxonomy.prompts import CategoryInfo
from app.modules.taxonomy.schemas import (
    TaxonomyAssignmentResponse,
    TaxonomyBreadcrumbResponse,
    TaxonomyCategoryDeleteResponse,
    TaxonomyCategoryResponse,
    TaxonomyCategoryTreeItem,
    TaxonomyInboxReclassifyResponse,
    TaxonomyJobMetricsResponse,
    TaxonomyJobStatusCountResponse,
    TaxonomyProfileResponse,
    TaxonomySettingsResponse,
)
from app.modules.vectorization.api import delete_source_vectors, enqueue_vectorization
from app.modules.vectorization.contracts import (
    VectorizationSubject,
    build_taxonomy_category_profile_vector_subject,
)
from app.platform.storage.service import StorageBackend

USER_PRIORITY = 200
INBOX_RECLASSIFY_PRIORITY = 20


class TaxonomyService:
    def __init__(self, session: AsyncSession, *, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.repository = TaxonomyRepository(session)

    # --- categories ------------------------------------------------------------------------
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
        slug = _validate_slug(slug)
        name = _validate_name(name)
        parent = None
        if parent_id is not None:
            parent = await self.repository.get_category(
                owner_user_id=owner_user_id, category_id=parent_id
            )
            if parent is None:
                raise TaxonomyNotFoundError
            if parent.is_archived:
                raise TaxonomyConflictError
        path = f"{parent.path}/{slug}" if parent is not None else slug
        await self._ensure_unique_category(
            owner_user_id=owner_user_id, parent_id=parent_id, slug=slug, path=path
        )
        category = TaxonomyCategory(
            id=str(uuid4()),
            owner_user_id=owner_user_id,
            parent_id=parent_id,
            slug=slug,
            name=name,
            description=description,
            path=path,
            depth=parent.depth + 1 if parent is not None else 0,
            sort_order=sort_order,
            source=source,
            is_system=is_system,
        )
        self.session.add(category)
        self.session.add(
            profile_for_new_category(
                category,
                profile_source="template" if source in {"template", "system"} else "generated",
            )
        )
        await self.session.flush()
        await self._index_profile(owner_user_id=owner_user_id, category_id=category.id)
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
    ) -> TaxonomyCategory | None:
        """Find or create every segment of `a/b/c`. Does not commit."""
        if not raw_path:
            return None
        segments = [category_slug(segment) for segment in raw_path.split("/") if segment.strip()]
        if not segments:
            return None
        prefixes = ["/".join(segments[: index + 1]) for index in range(len(segments))]
        existing = {
            category.path: category
            for category in await self.repository.list_categories_by_paths(
                owner_user_id=owner_user_id, paths=prefixes
            )
        }
        parent: TaxonomyCategory | None = None
        for segment, path in zip(segments, prefixes, strict=True):
            category = existing.get(path)
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
        return parent

    async def get_category(self, *, owner_user_id: str, category_id: str) -> TaxonomyCategory:
        category = await self.repository.get_category(
            owner_user_id=owner_user_id, category_id=category_id
        )
        if category is None:
            raise TaxonomyNotFoundError
        return category

    async def search_categories(
        self, *, owner_user_id: str, query_text: str, include_archived: bool
    ) -> list[TaxonomyCategory]:
        query_text = query_text.strip()
        if not query_text:
            raise TaxonomyValidationError
        return await self.repository.search_categories(
            owner_user_id=owner_user_id, query_text=query_text, include_archived=include_archived
        )

    async def get_breadcrumbs(
        self, *, owner_user_id: str, category_id: str
    ) -> list[TaxonomyBreadcrumbResponse]:
        category = await self.get_category(owner_user_id=owner_user_id, category_id=category_id)
        return await self._breadcrumbs(owner_user_id=owner_user_id, path=category.path)

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
            category.name = _validate_name(name)
        if description is not None:
            category.description = description
        if sort_order is not None:
            category.sort_order = sort_order
        if is_archived is not None:
            category.is_archived = is_archived
        if slug is not None and slug != category.slug:
            if await self.repository.has_children(
                owner_user_id=owner_user_id, category_id=category.id, active_only=False
            ):
                raise TaxonomyConflictError
            new_slug = _validate_slug(slug)
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
        await self._index_profile(owner_user_id=owner_user_id, category_id=category.id)
        await self.session.commit()
        await self.session.refresh(category)
        return category

    async def archive_category(self, *, owner_user_id: str, category_id: str) -> None:
        category = await self.get_category(owner_user_id=owner_user_id, category_id=category_id)
        if category.is_system:
            raise TaxonomyConflictError
        if await self.repository.has_children(
            owner_user_id=owner_user_id, category_id=category_id, active_only=True
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
        storage: StorageBackend,
    ) -> TaxonomyCategoryDeleteResponse:
        """Archive a category subtree and move its notes to the inbox (or delete them)."""
        category = await self.get_category(owner_user_id=owner_user_id, category_id=category_id)
        if category.is_system:
            raise TaxonomyConflictError
        if delete_notes and (
            confirm_category_name != category.name or confirm_delete_notes_text != category.path
        ):
            raise TaxonomyValidationError
        inbox = await self.repository.get_category_by_path(
            owner_user_id=owner_user_id, path=INBOX_PATH, include_archived=False
        )
        if inbox is None:
            raise TaxonomyNotFoundError
        subtree = await self.repository.list_subtree(
            owner_user_id=owner_user_id, path=category.path, include_archived=False
        )
        affected = await self.repository.list_current_assignments_in_paths(
            owner_user_id=owner_user_id, paths=[item.path for item in subtree]
        )
        content_ids = [assignment.content_object_id for assignment in affected]
        deleted_notes_count = 0
        moved_notes_count = 0
        if delete_notes and content_ids:
            # Imported lazily: content imports this module.
            from app.modules.content.deletion import NoteDeleter
            from app.modules.content.infrastructure.repositories import ContentRepository
            from app.modules.content.models import ContentObject

            slugs = list(
                await self.session.scalars(
                    select(ContentObject.slug).where(
                        ContentObject.owner_user_id == owner_user_id,
                        ContentObject.id.in_(content_ids),
                    )
                )
            )
            if slugs:
                await NoteDeleter(
                    self.session,
                    storage,
                    repository=ContentRepository(self.session),
                    taxonomy=self,
                ).delete_notes(owner_user_id=owner_user_id, slugs=slugs)
                deleted_notes_count = len(slugs)
        elif content_ids:
            await self.session.execute(
                update(TaxonomyContentAssignment)
                .where(
                    TaxonomyContentAssignment.owner_user_id == owner_user_id,
                    TaxonomyContentAssignment.content_object_id.in_(content_ids),
                    TaxonomyContentAssignment.is_current.is_(True),
                )
                .values(is_current=False, status=TaxonomyAssignmentStatus.OVERRIDDEN.value)
            )
            reasoning = f"Category {category.path} was deleted; moved to inbox."
            self.session.add_all(
                TaxonomyContentAssignment(
                    owner_user_id=owner_user_id,
                    content_object_id=content_object_id,
                    category_id=inbox.id,
                    status=TaxonomyAssignmentStatus.ACCEPTED.value,
                    confidence=1.0,
                    reasoning=reasoning,
                    assigned_by="system",
                    alternatives=[],
                    category_name_snapshot=inbox.name,
                    category_path_snapshot=inbox.path,
                    is_current=True,
                )
                for content_object_id in content_ids
            )
            await touch_content_objects(self.session, content_ids)
            moved_notes_count = len(content_ids)
        for item in subtree:
            item.is_archived = True
            await delete_source_vectors(
                self.session,
                owner_user_id=owner_user_id,
                source="taxonomy",
                source_type="category_profile",
                source_id=item.id,
            )
        await self.session.commit()
        return TaxonomyCategoryDeleteResponse(
            category_id=category.id,
            archived_categories_count=len(subtree),
            moved_notes_count=moved_notes_count,
            deleted_notes_count=deleted_notes_count,
        )

    async def restore_category(self, *, owner_user_id: str, category_id: str) -> TaxonomyCategory:
        category = await self.get_category(owner_user_id=owner_user_id, category_id=category_id)
        if category.parent_id is not None:
            parent = await self.repository.get_category(
                owner_user_id=owner_user_id, category_id=category.parent_id
            )
            if parent is None or parent.is_archived:
                raise TaxonomyConflictError
        category.is_archived = False
        await self._index_profile(owner_user_id=owner_user_id, category_id=category.id)
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
            owner_user_id=owner_user_id, include_archived=include_archived
        )
        by_parent: dict[str | None, list[TaxonomyCategory]] = {}
        by_id: dict[str, TaxonomyCategory] = {}
        for category in categories:
            by_parent.setdefault(category.parent_id, []).append(category)
            by_id[category.id] = category
        for children in by_parent.values():
            children.sort(key=lambda item: (item.sort_order, item.name.casefold()))
        if root_id is None:
            roots, base_depth = by_parent.get(None, []), 0
        else:
            root = by_id.get(root_id)
            if root is None:
                raise TaxonomyNotFoundError
            roots, base_depth = [root], root.depth

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

    # --- profiles --------------------------------------------------------------------------
    async def get_profile(self, *, owner_user_id: str, category_id: str) -> TaxonomyCategoryProfile:
        await self.get_category(owner_user_id=owner_user_id, category_id=category_id)
        profile = await self.repository.get_profile(category_id=category_id)
        if profile is None:
            raise TaxonomyNotFoundError
        return profile

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
            self.session.add(profile)
        profile.summary = summary
        profile.keywords = keywords
        profile.positive_examples = positive_examples
        profile.negative_examples = negative_examples
        profile.profile_source = "user_edited"
        await self._index_profile(owner_user_id=owner_user_id, category_id=category_id)
        await self.session.commit()
        await self.session.refresh(profile)
        return profile

    async def profile_improvement_context(
        self, *, owner_user_id: str, category_id: str
    ) -> tuple[CategoryInfo, list[CategoryInfo]]:
        """Category, its profile and its children, detached for use without a session."""
        category = await self.get_category(owner_user_id=owner_user_id, category_id=category_id)
        await self.session.refresh(category, ["profile"])
        children = await self.repository.list_children(
            owner_user_id=owner_user_id, parent_id=category.id
        )
        return category_info(category), [_plain_category_info(child) for child in children]

    async def build_category_profile_vector_subject(
        self, *, owner_user_id: str, category_id: str
    ) -> VectorizationSubject:
        """Document indexed for semantic classification (used by vectorization)."""
        category = await self.get_category(owner_user_id=owner_user_id, category_id=category_id)
        profile = await self.repository.get_profile(category_id=category.id)
        breadcrumbs = await self._breadcrumbs(owner_user_id=owner_user_id, path=category.path)
        lines = [
            f"Path: {' / '.join(item.name for item in breadcrumbs)}",
            f"Name: {category.name}",
            f"Description: {category.description or ''}",
            f"Summary: {profile.summary if profile is not None and profile.summary else ''}",
            "Keywords: " + (", ".join(profile.keywords) if profile is not None else ""),
            "Positive examples:",
        ]
        if profile is not None:
            lines.extend(f"- {example}" for example in profile.positive_examples)
        updated_at = category.updated_at
        if profile is not None and profile.updated_at > updated_at:
            updated_at = profile.updated_at
        return build_taxonomy_category_profile_vector_subject(
            owner_user_id=owner_user_id,
            category_id=category.id,
            category_path=category.path,
            category_depth=category.depth,
            source_text="\n".join(lines),
            source_updated_at=updated_at,
        )

    # --- user settings ---------------------------------------------------------------------
    async def get_user_settings(self, *, owner_user_id: str) -> TaxonomyUserSettings:
        """Stored settings, or unsaved defaults (never writes, safe inside any transaction)."""
        settings = await self.repository.get_settings(owner_user_id=owner_user_id)
        if settings is not None:
            return settings
        now = datetime.now(UTC)
        return TaxonomyUserSettings(
            owner_user_id=owner_user_id,
            category_profile_editing_enabled=False,
            trash_enabled=True,
            trash_retention_days=self.settings.trash_retention_days,
            tags_auto_apply_mode=AutomaticApplyMode.AUTO_APPLY_HIGH_CONFIDENCE.value,
            taxonomy_auto_apply_mode=AutomaticApplyMode.AUTO_APPLY_HIGH_CONFIDENCE.value,
            created_at=now,
            updated_at=now,
        )

    async def update_user_settings(
        self,
        *,
        owner_user_id: str,
        category_profile_editing_enabled: bool | None,
        trash_enabled: bool | None,
        trash_retention_days: int | None,
        tags_auto_apply_mode: str | None = None,
        taxonomy_auto_apply_mode: str | None = None,
    ) -> TaxonomyUserSettings:
        settings = await self.repository.get_settings(owner_user_id=owner_user_id)
        if settings is None:
            settings = await self.get_user_settings(owner_user_id=owner_user_id)
            self.session.add(settings)
        if category_profile_editing_enabled is not None:
            settings.category_profile_editing_enabled = category_profile_editing_enabled
        if trash_enabled is not None:
            settings.trash_enabled = trash_enabled
        if trash_retention_days is not None:
            settings.trash_retention_days = trash_retention_days
        if tags_auto_apply_mode is not None:
            settings.tags_auto_apply_mode = AutomaticApplyMode(tags_auto_apply_mode).value
        if taxonomy_auto_apply_mode is not None:
            settings.taxonomy_auto_apply_mode = AutomaticApplyMode(taxonomy_auto_apply_mode).value
        await self.session.commit()
        await self.session.refresh(settings)
        return settings

    # --- assignments -----------------------------------------------------------------------
    async def create_manual_assignment(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        category_id: str,
        reasoning: str | None,
        commit: bool = True,
    ) -> TaxonomyContentAssignment:
        await self._ensure_content(owner_user_id, content_object_id)
        category = await self.repository.get_category(
            owner_user_id=owner_user_id, category_id=category_id, include_archived=False
        )
        if category is None:
            raise TaxonomyNotFoundError
        assignment = await create_current_assignment(
            self.session,
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            category=category,
            status=TaxonomyAssignmentStatus.ACCEPTED.value,
            assigned_by="user",
            confidence=1.0,
            reasoning=reasoning,
        )
        self._record_feedback(
            owner_user_id, content_object_id, category.id, "manually_assigned", reasoning
        )
        if commit:
            await self.session.commit()
        return assignment

    async def assign_content_to_path(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        raw_path: str | None,
        reasoning: str | None,
        commit: bool = False,
    ) -> TaxonomyContentAssignment | None:
        category = await self.ensure_category_path(owner_user_id=owner_user_id, raw_path=raw_path)
        if category is None:
            return None
        return await self.create_manual_assignment(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            category_id=category.id,
            reasoning=reasoning,
            commit=commit,
        )

    async def list_assignments(
        self, *, owner_user_id: str, content_object_id: str
    ) -> list[TaxonomyContentAssignment]:
        await self._ensure_content(owner_user_id, content_object_id)
        return await self.repository.list_assignments(
            owner_user_id=owner_user_id, content_object_id=content_object_id
        )

    async def get_current_assignment(
        self, *, owner_user_id: str, content_object_id: str
    ) -> TaxonomyContentAssignment | None:
        return await self.repository.get_current_assignment(
            owner_user_id=owner_user_id, content_object_id=content_object_id
        )

    async def list_review_assignments(
        self, *, owner_user_id: str, limit: int = 50, offset: int = 0
    ) -> list[TaxonomyContentAssignment]:
        return await self.repository.list_review_assignments(
            owner_user_id=owner_user_id, limit=limit, offset=offset
        )

    async def accept_assignment(
        self, *, owner_user_id: str, content_object_id: str, assignment_id: str
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
        assignment.status = TaxonomyAssignmentStatus.ACCEPTED.value
        assignment.is_current = True
        assignment.category_name_snapshot = category.name
        assignment.category_path_snapshot = category.path
        self._record_feedback(
            owner_user_id, content_object_id, category.id, "accepted", assignment.reasoning
        )
        await touch_content_objects(self.session, [content_object_id])
        await self.session.commit()
        await self.session.refresh(assignment)
        return assignment

    async def reject_assignment(
        self, *, owner_user_id: str, content_object_id: str, assignment_id: str
    ) -> TaxonomyContentAssignment:
        assignment = await self._load_assignment(owner_user_id, content_object_id, assignment_id)
        assignment.status = TaxonomyAssignmentStatus.REJECTED.value
        assignment.is_current = False
        self._record_feedback(
            owner_user_id,
            content_object_id,
            assignment.category_id,
            "rejected",
            assignment.reasoning,
        )
        await touch_content_objects(self.session, [content_object_id])
        await self.session.commit()
        await self.session.refresh(assignment)
        return assignment

    # --- jobs ------------------------------------------------------------------------------
    async def enqueue_classification_job(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        priority: int = USER_PRIORITY,
        correlation_id: str | None = None,
    ) -> str:
        """Queue (re)classification. Does not commit."""
        await self._ensure_content(owner_user_id, content_object_id)
        return await self.repository.enqueue_job(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            priority=priority,
            max_attempts=self.settings.worker_max_job_attempts,
            correlation_id=correlation_id,
        )

    async def enqueue_inbox_reclassification_jobs(
        self, *, owner_user_id: str
    ) -> TaxonomyInboxReclassifyResponse:
        inbox = await self.repository.get_category_by_path(
            owner_user_id=owner_user_id, path=INBOX_PATH, include_archived=False
        )
        if inbox is None:
            raise TaxonomyNotFoundError
        content_ids = await self.repository.inbox_content_ids(owner_user_id=owner_user_id)
        await upsert_content_jobs(
            self.session,
            TaxonomyClassificationJob,
            owner_user_id=owner_user_id,
            content_object_ids=content_ids,
            job_type=CLASSIFY_CONTENT_JOB,
            priority=INBOX_RECLASSIFY_PRIORITY,
            max_attempts=self.settings.worker_max_job_attempts,
            source_event_id=None,
            correlation_id=str(uuid4()),
        )
        await self.session.commit()
        return TaxonomyInboxReclassifyResponse(enqueued_count=len(content_ids))

    async def list_classification_jobs(
        self, *, owner_user_id: str, content_object_id: str
    ) -> list[TaxonomyClassificationJob]:
        await self._ensure_content(owner_user_id, content_object_id)
        return await self.repository.list_classification_jobs_for_content(
            owner_user_id=owner_user_id, content_object_id=content_object_id
        )

    async def job_metrics(self, *, owner_user_id: str) -> TaxonomyJobMetricsResponse:
        rows = await self.repository.count_jobs_by_status(owner_user_id=owner_user_id)
        return TaxonomyJobMetricsResponse(
            jobs_by_status=[
                TaxonomyJobStatusCountResponse(status=status, count=count) for status, count in rows
            ],
            proposals_pending=await self.repository.count_pending_proposals(
                owner_user_id=owner_user_id
            ),
        )

    # --- onboarding ------------------------------------------------------------------------
    async def initialize_from_interests(
        self,
        *,
        owner_user_id: str,
        interest_slugs: list[str],
        custom_description: str | None,
        ai: AIClient | None,
    ) -> InitializeTaxonomyResult:
        """Create the initial tree. The optional AI call runs with no transaction open."""
        if await self.repository.has_categories(owner_user_id=owner_user_id):
            raise TaxonomyConflictError
        selected = list(dict.fromkeys(slug.strip() for slug in interest_slugs if slug.strip()))
        description = custom_description.strip() if custom_description else None
        if not selected and not description:
            raise TaxonomyValidationError
        tree = build_interest_tree(selected)
        if description:
            await self.session.commit()  # release the DB connection during the AI call
            tree.extend(await custom_interest_tree(ai, self.settings, description))
            if await self.repository.has_categories(owner_user_id=owner_user_id):
                raise TaxonomyConflictError
        created, profiles = await create_categories_from_tree(
            self.session, owner_user_id=owner_user_id, tree=tree
        )
        await self.session.commit()
        return InitializeTaxonomyResult(
            owner_user_id=owner_user_id,
            template_slug="interests",
            created_categories_count=created,
            created_profiles_count=profiles,
        )

    # --- responses -------------------------------------------------------------------------
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

    # --- helpers ---------------------------------------------------------------------------
    async def _breadcrumbs(
        self, *, owner_user_id: str, path: str
    ) -> list[TaxonomyBreadcrumbResponse]:
        parts = path.split("/")
        prefixes = ["/".join(parts[: index + 1]) for index in range(len(parts))]
        by_path = {
            item.path: item
            for item in await self.repository.list_categories_by_paths(
                owner_user_id=owner_user_id, paths=prefixes
            )
        }
        return [
            TaxonomyBreadcrumbResponse(
                id=by_path[prefix].id, name=by_path[prefix].name, path=prefix
            )
            for prefix in prefixes
            if prefix in by_path
        ]

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
        ) or await self.repository.category_path_exists(
            owner_user_id=owner_user_id, path=path, except_category_id=except_category_id
        ):
            raise TaxonomyConflictError

    async def _ensure_content(self, owner_user_id: str, content_object_id: str) -> None:
        if not await self.repository.content_exists(
            owner_user_id=owner_user_id, content_object_id=content_object_id
        ):
            raise TaxonomyNotFoundError

    async def _load_assignment(
        self, owner_user_id: str, content_object_id: str, assignment_id: str
    ) -> TaxonomyContentAssignment:
        assignment = await self.repository.get_assignment(
            owner_user_id=owner_user_id,
            content_object_id=content_object_id,
            assignment_id=assignment_id,
        )
        if assignment is None:
            raise TaxonomyNotFoundError
        return assignment

    async def _index_profile(self, *, owner_user_id: str, category_id: str) -> None:
        await enqueue_vectorization(
            self.session,
            owner_user_id=owner_user_id,
            source="taxonomy",
            source_type="category_profile",
            source_id=category_id,
            priority=USER_PRIORITY,
        )

    def _record_feedback(
        self,
        owner_user_id: str,
        content_object_id: str,
        category_id: str | None,
        action: str,
        reason: str | None,
    ) -> None:
        self.session.add(
            ClassificationFeedback(
                owner_user_id=owner_user_id,
                content_object_id=content_object_id,
                target_type="taxonomy",
                target_id=category_id,
                action=action,
                reason=reason,
                source="user",
            )
        )


def _validate_slug(slug: str) -> str:
    value = slug.strip()
    if not value or not CATEGORY_SLUG_RE.fullmatch(value):
        raise TaxonomyValidationError
    return value


def _validate_name(name: str) -> str:
    value = name.strip()
    if not value:
        raise TaxonomyValidationError
    return value


def _plain_category_info(category: TaxonomyCategory) -> CategoryInfo:
    """CategoryInfo without profile data (avoids loading child profiles)."""
    return CategoryInfo(
        id=category.id,
        parent_id=category.parent_id,
        name=category.name,
        path=category.path,
        depth=category.depth,
        sort_order=category.sort_order,
        description=category.description,
        summary=None,
        keywords=(),
        positive_examples=(),
        negative_examples=(),
    )
