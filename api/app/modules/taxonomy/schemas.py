from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

TaxonomyCategorySource = Literal[
    "template",
    "user",
    "system",
    "legacy_migration",
    "onboarding",
    "llm",
]
AssignmentStatus = Literal["proposed", "accepted", "rejected", "overridden"]
AssignedBy = Literal["user", "system", "llm", "migration"]
TaxonomyClassificationMode = Literal["semantic_only", "llm_judge"]
TaxonomyClassificationDecisionStatus = Literal["accepted", "proposed", "no_assignment"]


class TaxonomyCategoryCreateRequest(BaseModel):
    parent_id: str | None = Field(default=None, max_length=36)
    slug: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    sort_order: int = 100


class TaxonomyCategoryUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    slug: str | None = Field(default=None, min_length=1, max_length=255)
    sort_order: int | None = None
    is_archived: bool | None = None
    parent_id: str | None = Field(default=None, exclude=True)

    @field_validator("parent_id")
    @classmethod
    def reject_parent_update(cls, value: str | None) -> str | None:
        if value is not None:
            raise ValueError("parent_id cannot be updated")
        return value


class TaxonomyCategoryResponse(BaseModel):
    id: str
    owner_user_id: str
    parent_id: str | None
    slug: str
    name: str
    description: str | None
    path: str
    depth: int
    sort_order: int
    source: TaxonomyCategorySource
    is_system: bool
    is_archived: bool
    created_at: datetime
    updated_at: datetime


class TaxonomyBreadcrumbResponse(BaseModel):
    id: str
    name: str
    path: str


class TaxonomyCategoryTreeItem(BaseModel):
    id: str
    name: str
    slug: str
    path: str
    depth: int
    description: str | None
    is_system: bool
    is_archived: bool
    children: list[TaxonomyCategoryTreeItem] = Field(default_factory=list)


class TaxonomyProfilePutRequest(BaseModel):
    summary: str | None = None
    keywords: list[str] = Field(default_factory=list)
    positive_examples: list[str] = Field(default_factory=list)
    negative_examples: list[str] = Field(default_factory=list)


class TaxonomyProfileResponse(BaseModel):
    id: str
    category_id: str
    summary: str | None
    keywords: list[str]
    positive_examples: list[str]
    negative_examples: list[str]
    created_at: datetime
    updated_at: datetime


class TaxonomyAssignmentCreateRequest(BaseModel):
    category_id: str = Field(max_length=36)
    reasoning: str | None = None


class TaxonomyClassificationRequest(BaseModel):
    mode: TaxonomyClassificationMode = "semantic_only"
    candidate_limit: int = Field(default=5, ge=1, le=20)
    dry_run: bool = False


class TaxonomyClassificationCategoryResponse(BaseModel):
    id: str
    name: str
    path: str


class TaxonomyClassificationCandidateResponse(BaseModel):
    category_id: str
    category_name: str
    category_path: str
    score: float
    chunk_id: str


class TaxonomyLLMDecisionResponse(BaseModel):
    selected_category_id: str | None
    confidence: float = Field(ge=0, le=1)
    should_assign: bool
    status: TaxonomyClassificationDecisionStatus
    reasoning: str
    alternatives: list[dict[str, object]] = Field(default_factory=list)


class TaxonomyClassificationResponse(BaseModel):
    content_object_id: str
    mode: TaxonomyClassificationMode
    dry_run: bool
    assigned: bool
    assignment_id: str | None
    selected_category: TaxonomyClassificationCategoryResponse | None
    status: TaxonomyClassificationDecisionStatus
    confidence: float | None
    reasoning: str | None
    semantic_candidates: list[TaxonomyClassificationCandidateResponse]
    classification_text_preview: str
    llm_decision: TaxonomyLLMDecisionResponse | None = None
    would_assign: bool
    would_status: TaxonomyClassificationDecisionStatus
    would_category: TaxonomyClassificationCategoryResponse | None


class TaxonomyAssignmentResponse(BaseModel):
    id: str
    content_object_id: str
    category_id: str
    category_path: str
    category_name_snapshot: str
    category_path_snapshot: str
    status: AssignmentStatus
    confidence: float | None
    reasoning: str | None
    assigned_by: AssignedBy
    alternatives: list[dict[str, object]]
    is_current: bool
    created_at: datetime
    updated_at: datetime


class TaxonomyClassificationJobResponse(BaseModel):
    id: str
    content_object_id: str
    job_type: str
    status: str
    attempts: int
    max_attempts: int
    result_status: str | None
    assignment_id: str | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class TaxonomyClassificationJobListResponse(BaseModel):
    items: list[TaxonomyClassificationJobResponse]


class TaxonomyTemplateSummaryResponse(BaseModel):
    id: str
    slug: str
    name: str
    description: str | None
    is_active: bool


class TaxonomyInterestOptionResponse(BaseModel):
    slug: str
    name: str
    description: str


class TaxonomyTemplateTreeItem(BaseModel):
    id: str
    slug: str
    name: str
    description: str | None
    path: str
    depth: int
    sort_order: int
    profile_summary: str | None
    profile_keywords: list[str]
    profile_positive_examples: list[str]
    profile_negative_examples: list[str]
    children: list[TaxonomyTemplateTreeItem] = Field(default_factory=list)


class TaxonomyTemplateDetailResponse(TaxonomyTemplateSummaryResponse):
    tree: list[TaxonomyTemplateTreeItem]


class TaxonomyInitializeRequest(BaseModel):
    template_slug: str = Field(min_length=1, max_length=255)


class TaxonomyInterestInitializeRequest(BaseModel):
    interest_slugs: list[str] = Field(default_factory=list, max_length=12)
    custom_description: str | None = Field(default=None, max_length=2000)

    @field_validator("interest_slugs")
    @classmethod
    def normalize_interest_slugs(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class TaxonomyInitializeResponse(BaseModel):
    owner_user_id: str
    template_slug: str
    created_categories_count: int
    created_profiles_count: int
