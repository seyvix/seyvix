from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.tags.contracts import (
    AssignmentCreatedByType,
    AssignmentSource,
    AssignmentStatus,
    TagCreatedByType,
    TagSource,
)


class TagCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    tag_kind: str | None = Field(default=None, max_length=64)
    aliases: list[str] = Field(default_factory=list, max_length=50)


class TagUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    tag_kind: str | None = Field(default=None, max_length=64)
    aliases: list[str] | None = Field(default=None, max_length=50)
    is_archived: bool | None = None


class TagMergeRequest(BaseModel):
    target_tag_id: str = Field(min_length=1, max_length=36)


class TagResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: str | None
    tag_kind: str | None
    aliases: list[str]
    created_by_type: TagCreatedByType
    created_by_user_id: str | None
    source: TagSource
    source_detail: dict[str, object]
    confidence: float | None
    is_archived: bool
    created_at: datetime
    updated_at: datetime


class ManualAssignTagRequest(BaseModel):
    tag_id: str = Field(min_length=1, max_length=36)
    reasoning: str | None = None


class ContentTagAssignmentResponse(BaseModel):
    id: str
    content_object_id: str
    tag: TagResponse
    status: AssignmentStatus
    assigned_by_type: AssignmentCreatedByType
    assigned_by_user_id: str | None
    source: AssignmentSource
    source_detail: dict[str, object]
    confidence: float | None
    reasoning: str | None
    created_at: datetime
    updated_at: datetime


class SuggestContentTagsRequest(BaseModel):
    dry_run: bool = False
    max_tags: int = Field(default=8, ge=1, le=50)


class ContentTagSuggestionResponse(BaseModel):
    name: str
    slug: str
    confidence: float
    reasoning: str | None


class ContentTagDryRunResponse(BaseModel):
    content_object_id: str
    suggestions: list[ContentTagSuggestionResponse]


class TaggingJobResponse(BaseModel):
    job_id: str
    status: str


class TaggingJobDetailResponse(BaseModel):
    id: str
    content_object_id: str
    job_type: str
    status: str
    attempts: int
    max_attempts: int
    source_event_id: str | None
    correlation_id: str | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class TaggingJobListResponse(BaseModel):
    items: list[TaggingJobDetailResponse]


class TagReviewQueueResponse(BaseModel):
    items: list[ContentTagAssignmentResponse]


class JobStatusCountResponse(BaseModel):
    status: str
    count: int


class TagsJobMetricsResponse(BaseModel):
    jobs_by_status: list[JobStatusCountResponse]
    suggestions_pending: int
