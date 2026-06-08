from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.content.infrastructure.repositories import content_object_load_options
from app.modules.content.models import ContentObject
from app.modules.vectorization.models import (
    VectorizationChunk,
    VectorizationEmbedding,
    VectorizationSource,
)


@dataclass(frozen=True, slots=True)
class SourceEmbedding:
    vector: list[float]


class RecommendationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_content_object_embeddings(
        self,
        *,
        owner_user_id: str,
        content_object_id: str,
        provider: str,
        model: str,
        dimensions: int,
    ) -> list[SourceEmbedding]:
        statement = (
            select(VectorizationEmbedding.embedding)
            .join(VectorizationChunk, VectorizationChunk.id == VectorizationEmbedding.chunk_id)
            .join(
                VectorizationSource,
                VectorizationSource.id == VectorizationChunk.source_record_id,
            )
            .where(
                VectorizationSource.owner_user_id == owner_user_id,
                VectorizationChunk.owner_user_id == owner_user_id,
                VectorizationEmbedding.owner_user_id == owner_user_id,
                VectorizationSource.source == "content",
                VectorizationSource.source_type == "content_object",
                VectorizationSource.source_id == content_object_id,
                VectorizationSource.status == "synced",
                VectorizationEmbedding.provider == provider,
                VectorizationEmbedding.model == model,
                VectorizationEmbedding.dimensions == dimensions,
            )
            .order_by(VectorizationChunk.chunk_index.asc())
        )
        vectors = list(await self.session.scalars(statement))
        return [SourceEmbedding(vector=list(cast(list[float], vector))) for vector in vectors]

    async def list_recommendable_content_objects(
        self,
        *,
        owner_user_id: str,
        content_object_ids: list[str],
    ) -> dict[str, ContentObject]:
        if not content_object_ids:
            return {}
        statement = (
            select(ContentObject)
            .options(*content_object_load_options())
            .where(
                ContentObject.owner_user_id == owner_user_id,
                ContentObject.id.in_(content_object_ids),
                ContentObject.deleted_at.is_(None),
            )
        )
        rows = list(await self.session.scalars(statement))
        return {item.id: item for item in rows}
