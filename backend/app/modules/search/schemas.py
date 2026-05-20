from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SearchMode = Literal["full_text", "semantic", "hybrid"]


class SearchFilters(BaseModel):
    source: str | None = Field(default=None, min_length=1, max_length=64)
    source_type: str | None = Field(default=None, min_length=1, max_length=64)
    source_id: str | None = Field(default=None, min_length=1, max_length=255)
    content_type: str | None = Field(default=None, min_length=1, max_length=64)
    content_types: list[str] = Field(default_factory=list, max_length=20)
    content_source: str | None = Field(default=None, min_length=1, max_length=64)
    source_provider: str | None = Field(default=None, min_length=1, max_length=64)
    source_kind: str | None = Field(default=None, min_length=1, max_length=64)
    telegram_chat_id: str | None = Field(default=None, min_length=1, max_length=255)
    telegram_chat_type: str | None = Field(default=None, min_length=1, max_length=64)
    telegram_author_id: str | None = Field(default=None, min_length=1, max_length=255)
    tags: list[str] = Field(default_factory=list, max_length=50)
    folder_path: str | None = Field(default=None, min_length=1, max_length=1024)
    is_favorite: bool | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    created_at_from: datetime | None = None
    created_at_to: datetime | None = None
    updated_at_from: datetime | None = None
    updated_at_to: datetime | None = None


class SemanticSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    source: str | None = Field(default=None, min_length=1, max_length=64)
    source_type: str | None = Field(default=None, min_length=1, max_length=64)
    source_id: str | None = Field(default=None, min_length=1, max_length=255)
    filters: SearchFilters | None = None
    limit: int = Field(default=10, ge=1, le=50)


class SemanticSearchResult(BaseModel):
    source: str
    source_type: str
    source_id: str
    external_id: str
    chunk_id: str
    chunk_external_id: str
    text: str
    metadata: dict[str, object]
    distance: float
    score: float


class SemanticSearchResponse(BaseModel):
    query: str
    results: list[SemanticSearchResult]


class HybridSearchRequest(SemanticSearchRequest):
    expand_query: bool | None = None
    mode: SearchMode = "hybrid"


class HybridSearchResult(BaseModel):
    source: str
    source_type: str
    source_id: str
    external_id: str
    chunk_id: str
    chunk_external_id: str
    text: str
    metadata: dict[str, object]
    distance: float | None = None
    score: float
    vector_score: float | None = None
    full_text_score: float | None = None
    vector_rank: int | None = None
    full_text_rank: int | None = None


class HybridSearchResponse(BaseModel):
    query: str
    expanded_queries: list[str] = Field(default_factory=list)
    results: list[HybridSearchResult]


class SearchHighlightRange(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(ge=0)


class SearchContentMatch(BaseModel):
    chunk_id: str
    chunk_external_id: str
    text: str
    score: float
    highlight_ranges: list[SearchHighlightRange] = Field(default_factory=list)
