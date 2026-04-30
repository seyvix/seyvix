from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.modules.search.schemas import SemanticSearchResult
from app.modules.vectorization.contracts import (
    VectorizedChunkSearchReader,
    build_vectorized_chunk_search_reader,
)
from app.modules.vectorization.infrastructure.embedding_providers import (
    EmbeddingProvider,
    build_embedding_provider,
)


class SearchValidationError(Exception):
    pass


class SemanticSearchService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        chunk_reader: VectorizedChunkSearchReader | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.embedding_provider = embedding_provider or build_embedding_provider(
            provider_name=self.settings.vector_embedding_provider,
            base_url=self.settings.vector_embedding_base_url,
            api_key=self.settings.vector_embedding_api_key,
            timeout_seconds=self.settings.vector_embedding_timeout_seconds,
        )
        self.chunk_reader = chunk_reader or build_vectorized_chunk_search_reader(session)

    async def semantic_search(
        self,
        *,
        owner_user_id: str,
        query: str,
        limit: int,
        source: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
    ) -> list[SemanticSearchResult]:
        normalized_query = query.strip()
        if not normalized_query:
            raise SearchValidationError("Search query must not be empty.")
        query_embedding = (
            await self.embedding_provider.embed_texts(
                [normalized_query],
                model=self.settings.vector_embedding_model,
                dimensions=self.settings.vector_embedding_dimensions,
            )
        )[0]
        matches = await self.chunk_reader.search_similar_chunks(
            owner_user_id=owner_user_id,
            query_embedding=query_embedding,
            provider=self.settings.vector_embedding_provider,
            model=self.settings.vector_embedding_model,
            dimensions=self.settings.vector_embedding_dimensions,
            limit=limit,
            source=source,
            source_type=source_type,
            source_id=source_id,
        )
        return [SemanticSearchResult.model_validate(match.model_dump()) for match in matches]
