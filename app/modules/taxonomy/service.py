from __future__ import annotations

import re
from dataclasses import dataclass
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.taxonomy.infrastructure.repositories import TaxonomyRepository
from app.modules.taxonomy.models import (
    TaxonomyCategory,
    TaxonomyCategoryProfile,
    TaxonomyContentAssignment,
    TaxonomyTemplate,
    TaxonomyTemplateCategory,
)
from app.modules.taxonomy.schemas import (
    TaxonomyAssignmentResponse,
    TaxonomyBreadcrumbResponse,
    TaxonomyCategoryResponse,
    TaxonomyCategoryTreeItem,
    TaxonomyProfileResponse,
    TaxonomyTemplateDetailResponse,
    TaxonomyTemplateSummaryResponse,
    TaxonomyTemplateTreeItem,
)
from app.modules.vectorization.contracts import (
    VectorizationSubject,
    build_taxonomy_category_profile_vector_subject,
)

SLUG_PATTERN = re.compile(r"^[a-z0-9_-]+$")


class TaxonomyNotFoundError(Exception):
    pass


class TaxonomyConflictError(Exception):
    pass


class TaxonomyValidationError(Exception):
    pass


@dataclass(slots=True)
class InitializeTaxonomyResult:
    owner_user_id: str
    template_slug: str
    created_categories_count: int
    created_profiles_count: int


class TaxonomyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = TaxonomyRepository(session)

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
        await self.get_category(owner_user_id=owner_user_id, category_id=category_id)
        profile = await self.repository.get_profile(category_id=category_id)
        if profile is None:
            profile = TaxonomyCategoryProfile(category_id=category_id)
            self.repository.add_profile(profile)
        profile.summary = summary
        profile.keywords = keywords
        profile.positive_examples = positive_examples
        profile.negative_examples = negative_examples
        await self.session.commit()
        await self.session.refresh(profile)
        return profile

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

    async def list_templates(self) -> list[TaxonomyTemplate]:
        await self._ensure_templates_seeded()
        return await self.repository.list_templates()

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
            created_profiles += 1
        await self.session.commit()
        return InitializeTaxonomyResult(
            owner_user_id=owner_user_id,
            template_slug=template.slug,
            created_categories_count=len(created_by_template_id),
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
            alternatives=[],
            category_name_snapshot=category.name,
            category_path_snapshot=category.path,
            is_current=True,
        )
        self.repository.add_assignment(assignment)
        await self.session.flush()
        if commit:
            await self.session.commit()
            await self.session.refresh(assignment)
        return assignment

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
                        "description": f"Materials related to {name}.",
                        "path": path,
                        "depth": depth,
                        "sort_order": index * 10,
                        **cls._profile(name),
                    }
                )
                visit(node["children"], path, depth + 1)  # type: ignore[arg-type]

        visit(tree, "", 0)
        return flattened

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
