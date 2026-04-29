from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.shared.module_definitions import ModuleDefinition

MODULE = ModuleDefinition(
    name="vectorization",
    description="Chunking, embedding generation, and vector index synchronization pipelines.",
    public_contracts=[
        "chunker",
        "embedding-job",
        "vector-index",
        "taxonomy-category-profile-vector-subject",
    ],
    plugin_capabilities=["embedding_provider", "chunking_strategy"],
)


class VectorizationSubject(BaseModel):
    external_id: str
    source_text: str
    metadata: dict[str, str | int]
    source_updated_at: datetime
    dirty_key: str


class VectorizationDocumentInput(BaseModel):
    owner_user_id: str = Field(min_length=1)
    source: str = Field(min_length=1, max_length=64)
    source_type: str = Field(min_length=1, max_length=64)
    source_id: str = Field(min_length=1, max_length=255)
    external_id: str = Field(min_length=1, max_length=512)
    text: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    chunking_strategy: str = Field(min_length=1, max_length=64)
    representation_type: str = Field(min_length=1, max_length=64)
    source_updated_at: datetime
    dirty_key: str = Field(min_length=1, max_length=255)

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Vectorization document text must not be empty.")
        return value


class VectorizationIndexRequest(BaseModel):
    owner_user_id: str = Field(min_length=1)
    source: str = Field(min_length=1, max_length=64)
    source_type: str = Field(min_length=1, max_length=64)
    source_id: str = Field(min_length=1, max_length=255)
    priority: int = Field(default=100, ge=0, le=1000)
    reason: str | None = Field(default=None, max_length=255)


def vectorization_document_from_subject(
    *,
    owner_user_id: str,
    source: str,
    source_type: str,
    source_id: str,
    chunking_strategy: str,
    representation_type: str,
    subject: VectorizationSubject,
) -> VectorizationDocumentInput:
    metadata: dict[str, Any] = dict(subject.metadata)
    return VectorizationDocumentInput(
        owner_user_id=owner_user_id,
        source=source,
        source_type=source_type,
        source_id=source_id,
        external_id=subject.external_id,
        text=subject.source_text,
        metadata=metadata,
        chunking_strategy=chunking_strategy,
        representation_type=representation_type,
        source_updated_at=subject.source_updated_at,
        dirty_key=subject.dirty_key,
    )


def build_taxonomy_category_profile_vector_subject(
    *,
    owner_user_id: str,
    category_id: str,
    category_path: str,
    category_depth: int,
    source_text: str,
    source_updated_at: datetime,
) -> VectorizationSubject:
    return VectorizationSubject(
        external_id=f"taxonomy_category_profile:{category_id}",
        source_text=source_text,
        metadata={
            "owner_user_id": owner_user_id,
            "category_id": category_id,
            "category_path": category_path,
            "category_depth": category_depth,
            "source": "taxonomy",
        },
        source_updated_at=source_updated_at,
        dirty_key=source_updated_at.isoformat(),
    )
