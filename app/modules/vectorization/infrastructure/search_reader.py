from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.vectorization.contracts import VectorizedChunkSearchResult
from app.modules.vectorization.models import (
    VectorizationChunk,
    VectorizationEmbedding,
    VectorizationSource,
)


class PgVectorizedChunkSearchReader:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search_similar_chunks(
        self,
        *,
        owner_user_id: str,
        query_embedding: list[float],
        provider: str,
        model: str,
        dimensions: int,
        limit: int,
    ) -> list[VectorizedChunkSearchResult]:
        distance = VectorizationEmbedding.embedding.cosine_distance(query_embedding).label(
            "distance"
        )
        query = (
            select(VectorizationChunk, VectorizationSource, distance)
            .join(
                VectorizationEmbedding,
                VectorizationEmbedding.chunk_id == VectorizationChunk.id,
            )
            .join(
                VectorizationSource,
                VectorizationSource.id == VectorizationChunk.source_record_id,
            )
            .where(
                VectorizationChunk.owner_user_id == owner_user_id,
                VectorizationEmbedding.owner_user_id == owner_user_id,
                VectorizationSource.owner_user_id == owner_user_id,
                VectorizationSource.status == "synced",
                VectorizationEmbedding.provider == provider,
                VectorizationEmbedding.model == model,
                VectorizationEmbedding.dimensions == dimensions,
            )
            .order_by(distance.asc())
            .limit(limit)
        )
        rows = (await self.session.execute(query)).all()
        results: list[VectorizedChunkSearchResult] = []
        for chunk, source, raw_distance in rows:
            distance_value = float(raw_distance)
            results.append(
                VectorizedChunkSearchResult(
                    source=source.source,
                    source_type=source.source_type,
                    source_id=source.source_id,
                    external_id=source.external_id,
                    chunk_id=chunk.id,
                    chunk_external_id=chunk.chunk_external_id,
                    text=chunk.text,
                    metadata=chunk.metadata_,
                    distance=distance_value,
                    score=1.0 - distance_value,
                )
            )
        return results
