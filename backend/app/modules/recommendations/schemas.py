from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.content.schemas import TagResponse


class RecommendedNoteItem(BaseModel):
    id: str
    slug: str
    kind: str
    media_type: str | None
    title: str
    score: float = Field(ge=0, le=1)
    matched_text: str
    tags: list[TagResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class NoteRecommendationsResponse(BaseModel):
    items: list[RecommendedNoteItem]
