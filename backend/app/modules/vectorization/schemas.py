from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class VectorizationIndexRequestBody(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    source_type: str = Field(min_length=1, max_length=64)
    source_id: str = Field(min_length=1, max_length=255)
    priority: int = Field(default=100, ge=0, le=1000)


class VectorizationIndexResponse(BaseModel):
    job_id: str
    status: str


class VectorizationReindexRequestBody(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    source_type: str = Field(min_length=1, max_length=64)
    priority: int = Field(default=100, ge=0, le=1000)


class VectorizationReindexResponse(BaseModel):
    job_count: int
    job_ids: list[str]


class VectorizationDeleteSourceVectorsRequestBody(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    source_type: str = Field(min_length=1, max_length=64)
    source_id: str = Field(min_length=1, max_length=255)


class VectorizationDeleteSourceVectorsResponse(BaseModel):
    status: str


class VectorizationJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source: str
    source_type: str
    source_id: str
    status: str
    priority: int
    attempts: int
    max_attempts: int
    run_after: datetime
    locked_at: datetime | None
    locked_by: str | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class VectorizationSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source: str
    source_type: str
    source_id: str
    content_hash: str
    chunk_count: int
    needs_embedding: bool
    embedding_model: str | None
    last_error: str | None
    indexed_at: datetime
    created_at: datetime
    updated_at: datetime


class VectorizationChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_record_id: str
    chunk_index: int
    text_hash: str
    token_count: int
    has_embedding: bool
    created_at: datetime
