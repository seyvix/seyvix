from __future__ import annotations

from pydantic import BaseModel, Field


class SemanticSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
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
