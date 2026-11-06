from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

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


class TagAssignmentStatus(StrEnum):
    SUGGESTED = "suggested"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    REMOVED = "removed"


class ContentTagSuggestion(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
