from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

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
