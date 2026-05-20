from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from app.shared.module_definitions import ModuleDefinition
from pydantic import BaseModel, Field

MODULE = ModuleDefinition(
    name="tags",
    description=(
        "Content tags with provenance, assignment states, LLM suggestions, and worker jobs."
    ),
    public_contracts=["tag", "content-tag-assignment", "content-tag-suggestion"],
    plugin_capabilities=["tags_reader", "tags_writer"],
)

TagCreatedByType = Literal["user", "llm", "system", "import", "migration"]
TagSource = Literal[
    "manual",
    "llm_suggested",
    "llm_auto_created",
    "imported",
    "system_seeded",
    "migration",
]
AssignmentStatus = Literal["suggested", "accepted", "rejected", "removed"]
AssignmentCreatedByType = Literal["user", "llm", "system", "migration"]
AssignmentSource = Literal[
    "manual",
    "llm_suggested",
    "llm_auto_applied",
    "imported",
    "system",
]
TaggingJobType = Literal["suggest_content_tags", "refresh_content_tags"]
TaggingJobStatus = Literal["pending", "processing", "succeeded", "failed", "cancelled", "stale"]


class TagAssignmentStatus(StrEnum):
    SUGGESTED = "suggested"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    REMOVED = "removed"


class TaggingJobStatusValue(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STALE = "stale"


class TagRef(BaseModel):
    id: str
    owner_user_id: str
    name: str
    slug: str
    description: str | None = None
    tag_kind: str | None = None
    aliases: list[str] = Field(default_factory=list)
    created_by_type: TagCreatedByType
    created_by_user_id: str | None = None
    source: TagSource
    source_detail: dict[str, object] = Field(default_factory=dict)
    confidence: float | None = None
    is_archived: bool
    created_at: datetime
    updated_at: datetime


class ContentTagAssignmentRef(BaseModel):
    id: str
    owner_user_id: str
    content_object_id: str
    tag_id: str
    status: AssignmentStatus
    assigned_by_type: AssignmentCreatedByType
    assigned_by_user_id: str | None = None
    source: AssignmentSource
    source_detail: dict[str, object] = Field(default_factory=dict)
    confidence: float | None = None
    reasoning: str | None = None
    created_at: datetime
    updated_at: datetime


class ContentTagSuggestion(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None


class ContentTaggingRequest(BaseModel):
    owner_user_id: str
    content_object_id: str
    max_tags: int = Field(default=8, ge=1, le=50)
