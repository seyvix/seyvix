from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.modules.llm.contracts import (
    LLMGenerationError,
    StructuredLLMGenerator,
    build_structured_llm_generator,
)
from app.modules.search.infrastructure.meilisearch import (
    MeilisearchSearchBackend,
    build_meilisearch_client,
)
from app.modules.search.schemas import (
    HybridSearchResponse,
    HybridSearchResult,
    SearchContentMatch,
    SearchFilters,
    SearchHighlightRange,
    SearchMode,
    SemanticSearchResult,
)
from app.modules.vectorization.contracts import (
    VectorizedChunkFullTextSearchResult,
    VectorizedChunkSearchFilters,
    VectorizedChunkSearchReader,
    VectorizedChunkSearchResult,
    build_vectorized_chunk_search_reader,
)
from app.modules.vectorization.infrastructure.embedding_providers import (
    EmbeddingProvider,
    build_embedding_provider,
)


class SearchValidationError(Exception):
    pass


@dataclass(slots=True)
class _HybridCandidate:
    source: str
    source_type: str
    source_id: str
    external_id: str
    chunk_id: str
    chunk_external_id: str
    text: str
    metadata: dict[str, object]
    score: float = 0
    distance: float | None = None
    vector_score: float | None = None
    full_text_score: float | None = None
    vector_rank: int | None = None
    full_text_rank: int | None = None

    def to_result(self) -> HybridSearchResult:
        return HybridSearchResult(
            source=self.source,
            source_type=self.source_type,
            source_id=self.source_id,
            external_id=self.external_id,
            chunk_id=self.chunk_id,
            chunk_external_id=self.chunk_external_id,
            text=self.text,
            metadata=self.metadata,
            distance=self.distance,
            score=self.score,
            vector_score=self.vector_score,
            full_text_score=self.full_text_score,
            vector_rank=self.vector_rank,
            full_text_rank=self.full_text_rank,
        )


class SemanticSearchService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        chunk_reader: VectorizedChunkSearchReader | None = None,
        llm_generator: StructuredLLMGenerator | None = None,
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
        self.llm_generator = llm_generator

    async def semantic_search(
        self,
        *,
        owner_user_id: str,
        query: str,
        limit: int,
        source: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        filters: SearchFilters | None = None,
    ) -> list[SemanticSearchResult]:
        normalized_query = _normalize_query(query)
        vector_filters = _to_vector_filters(
            filters=filters,
            source=source,
            source_type=source_type,
            source_id=source_id,
        )
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
            filters=vector_filters,
        )
        return [SemanticSearchResult.model_validate(match.model_dump()) for match in matches]

    async def hybrid_search(
        self,
        *,
        owner_user_id: str,
        query: str,
        limit: int,
        source: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        filters: SearchFilters | None = None,
        expand_query: bool | None = None,
        mode: SearchMode = "hybrid",
    ) -> HybridSearchResponse:
        normalized_query = _normalize_query(query)
        if self._should_use_meilisearch():
            candidate_limit = max(limit, limit * self.settings.search_hybrid_candidate_multiplier)
            backend = MeilisearchSearchBackend(
                client=build_meilisearch_client(self.settings),
                embedding_provider=self.embedding_provider,
                settings=self.settings,
            )
            results = await backend.search(
                owner_user_id=owner_user_id,
                query=normalized_query,
                limit=candidate_limit,
                mode=mode,
                filters=filters,
                source=source,
                source_type=source_type,
                source_id=source_id,
            )
            return HybridSearchResponse(
                query=normalized_query,
                expanded_queries=[normalized_query],
                results=results[:limit],
            )

        vector_filters = _to_vector_filters(
            filters=filters,
            source=source,
            source_type=source_type,
            source_id=source_id,
        )
        expanded_queries = await self._expanded_queries(
            normalized_query,
            expand_query=expand_query,
        )
        candidate_limit = max(limit, limit * self.settings.search_hybrid_candidate_multiplier)
        query_embeddings = await self.embedding_provider.embed_texts(
            expanded_queries,
            model=self.settings.vector_embedding_model,
            dimensions=self.settings.vector_embedding_dimensions,
        )
        candidates: dict[str, _HybridCandidate] = {}

        for query_embedding in query_embeddings:
            vector_matches = await self.chunk_reader.search_similar_chunks(
                owner_user_id=owner_user_id,
                query_embedding=query_embedding,
                provider=self.settings.vector_embedding_provider,
                model=self.settings.vector_embedding_model,
                dimensions=self.settings.vector_embedding_dimensions,
                limit=candidate_limit,
                filters=vector_filters,
            )
            for rank, match in enumerate(vector_matches, start=1):
                candidate = candidates.setdefault(
                    match.chunk_id,
                    _candidate_from_vector(match),
                )
                candidate.score += _rrf(rank, self.settings.search_rrf_k)
                candidate.vector_rank = _best_rank(candidate.vector_rank, rank)
                candidate.vector_score = _best_score(candidate.vector_score, match.score)
                candidate.distance = _best_distance(candidate.distance, match.distance)

        for expanded_query in expanded_queries:
            full_text_matches = await self.chunk_reader.search_full_text_chunks(
                owner_user_id=owner_user_id,
                query=expanded_query,
                limit=candidate_limit,
                search_config=self.settings.search_fts_config,
                filters=vector_filters,
            )
            for rank, full_text_match in enumerate(full_text_matches, start=1):
                candidate = candidates.setdefault(
                    full_text_match.chunk_id,
                    _candidate_from_full_text(full_text_match),
                )
                candidate.score += _rrf(rank, self.settings.search_rrf_k)
                candidate.full_text_rank = _best_rank(candidate.full_text_rank, rank)
                candidate.full_text_score = _best_score(
                    candidate.full_text_score,
                    full_text_match.full_text_score,
                )

        ranked = sorted(
            candidates.values(),
            key=lambda item: (
                item.score,
                item.vector_score or 0,
                item.full_text_score or 0,
                item.text,
            ),
            reverse=True,
        )
        return HybridSearchResponse(
            query=normalized_query,
            expanded_queries=expanded_queries,
            results=[candidate.to_result() for candidate in ranked[:limit]],
        )

    async def search_content_object_ids(
        self,
        *,
        owner_user_id: str,
        query: str,
        limit: int,
        mode: SearchMode,
        filters: SearchFilters | None = None,
    ) -> list[str]:
        matches_by_source_id = await self.search_content_object_matches(
            owner_user_id=owner_user_id,
            query=query,
            limit=limit,
            mode=mode,
            filters=filters,
        )
        return list(matches_by_source_id)

    async def search_content_object_matches(
        self,
        *,
        owner_user_id: str,
        query: str,
        limit: int,
        mode: SearchMode,
        filters: SearchFilters | None = None,
    ) -> dict[str, list[SearchContentMatch]]:
        normalized_query = _normalize_query(query)
        if self._should_use_meilisearch():
            backend = MeilisearchSearchBackend(
                client=build_meilisearch_client(self.settings),
                embedding_provider=self.embedding_provider,
                settings=self.settings,
            )
            results = await backend.search(
                owner_user_id=owner_user_id,
                query=normalized_query,
                limit=limit * self.settings.search_hybrid_candidate_multiplier,
                mode=mode,
                filters=filters,
                source="content",
                source_type="content_object",
            )
        elif mode == "full_text":
            vector_filters = _to_vector_filters(
                filters=filters,
                source="content",
                source_type="content_object",
                source_id=None,
            )
            results = [
                _candidate_from_full_text(item).to_result()
                for item in await self.chunk_reader.search_full_text_chunks(
                    owner_user_id=owner_user_id,
                    query=normalized_query,
                    limit=limit * self.settings.search_hybrid_candidate_multiplier,
                    search_config=self.settings.search_fts_config,
                    filters=vector_filters,
                )
            ]
        elif mode == "semantic":
            results = [
                HybridSearchResult.model_validate(item.model_dump())
                for item in await self.semantic_search(
                    owner_user_id=owner_user_id,
                    query=normalized_query,
                    limit=limit * self.settings.search_hybrid_candidate_multiplier,
                    source="content",
                    source_type="content_object",
                    filters=filters,
                )
            ]
        else:
            results = (
                await self.hybrid_search(
                    owner_user_id=owner_user_id,
                    query=normalized_query,
                    limit=limit * self.settings.search_hybrid_candidate_multiplier,
                    source="content",
                    source_type="content_object",
                    filters=filters,
                    expand_query=False,
                    mode="hybrid",
                )
            ).results

        return build_search_matches_by_source_id(
            query=normalized_query,
            results=results,
            max_matches_per_note=2,
            max_notes=limit,
        )

    async def _expanded_queries(
        self,
        query: str,
        *,
        expand_query: bool | None,
    ) -> list[str]:
        should_expand = (
            expand_query
            if expand_query is not None
            else self.settings.search_query_expansion_enabled
        )
        max_queries = max(1, self.settings.search_query_expansion_max_queries)
        if not should_expand or max_queries == 1:
            return [query]
        try:
            generator = self.llm_generator or build_structured_llm_generator()
            raw = await generator.generate_structured(
                prompt=(
                    "Rewrite the search query into short alternative queries that preserve intent "
                    "and improve recall. Return concise variants only.\n\n"
                    f"Query: {query}"
                ),
                schema={
                    "type": "object",
                    "properties": {
                        "queries": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 4000,
                            },
                            "maxItems": max_queries - 1,
                        }
                    },
                    "required": ["queries"],
                    "additionalProperties": False,
                },
                model_config={
                    "model": self.settings.search_query_expansion_model,
                    "temperature": 0.2,
                    "max_tokens": 512,
                },
            )
        except LLMGenerationError:
            return [query]
        return _dedupe_queries(query, raw.get("queries"), max_queries=max_queries)

    def _should_use_meilisearch(self) -> bool:
        return (
            self.settings.search_engine == "meilisearch"
            and self.settings.search_meilisearch_url is not None
        )


def _normalize_query(query: str) -> str:
    normalized_query = query.strip()
    if not normalized_query:
        raise SearchValidationError("Search query must not be empty.")
    return normalized_query


def build_search_matches_by_source_id(
    *,
    query: str,
    results: list[HybridSearchResult],
    max_matches_per_note: int,
    max_notes: int | None = None,
) -> dict[str, list[SearchContentMatch]]:
    terms = _highlight_terms(query)
    matches: dict[str, list[SearchContentMatch]] = {}
    for result in results:
        if result.source != "content" or result.source_type != "content_object":
            continue
        if result.source_id not in matches:
            if max_notes is not None and len(matches) >= max_notes:
                break
            matches[result.source_id] = []
        if len(matches[result.source_id]) >= max_matches_per_note:
            continue
        matches[result.source_id].append(
            SearchContentMatch(
                chunk_id=result.chunk_id,
                chunk_external_id=result.chunk_external_id,
                text=result.text.strip(),
                score=result.score,
                highlight_ranges=_highlight_ranges(result.text, terms),
            )
        )
    return matches


def _highlight_terms(query: str) -> list[str]:
    terms = []
    seen: set[str] = set()
    for term in re.findall(r"[0-9A-Za-zА-Яа-яЁё_]{2,}", query):
        normalized = term.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        terms.append(normalized)
    return sorted(terms, key=len, reverse=True)


def _highlight_ranges(text: str, terms: list[str]) -> list[SearchHighlightRange]:
    if not terms:
        return []
    lowered = text.casefold()
    raw_ranges: list[tuple[int, int]] = []
    for term in terms:
        start = 0
        while True:
            index = lowered.find(term, start)
            if index == -1:
                break
            raw_ranges.append((index, index + len(term)))
            start = index + len(term)
    ranges: list[SearchHighlightRange] = []
    occupied_until = -1
    for start, end in sorted(raw_ranges):
        if start < occupied_until:
            continue
        ranges.append(SearchHighlightRange(start=start, end=end))
        occupied_until = end
    return ranges


def _to_vector_filters(
    *,
    filters: SearchFilters | None,
    source: str | None,
    source_type: str | None,
    source_id: str | None,
) -> VectorizedChunkSearchFilters | None:
    if filters is None:
        if source is None and source_type is None and source_id is None:
            return None
        return VectorizedChunkSearchFilters(
            source=source,
            source_type=source_type,
            source_id=source_id,
        )
    content_types = [value.strip() for value in filters.content_types if value.strip()]
    if filters.content_type is not None and filters.content_type.strip():
        content_types.append(filters.content_type.strip())
    return VectorizedChunkSearchFilters(
        source=filters.source or source,
        source_type=filters.source_type or source_type,
        source_id=filters.source_id or source_id,
        content_types=content_types,
        content_source=filters.content_source,
        created_at_from=filters.created_at_from,
        created_at_to=filters.created_at_to,
        updated_at_from=filters.updated_at_from,
        updated_at_to=filters.updated_at_to,
    )


def _dedupe_queries(query: str, raw_queries: Any, *, max_queries: int) -> list[str]:
    queries = [query]
    seen = {query.casefold()}
    if isinstance(raw_queries, list):
        for raw_query in raw_queries:
            if not isinstance(raw_query, str):
                continue
            candidate = raw_query.strip()
            if not candidate or candidate.casefold() in seen:
                continue
            seen.add(candidate.casefold())
            queries.append(candidate)
            if len(queries) >= max_queries:
                break
    return queries


def _candidate_from_vector(match: VectorizedChunkSearchResult) -> _HybridCandidate:
    return _HybridCandidate(
        source=match.source,
        source_type=match.source_type,
        source_id=match.source_id,
        external_id=match.external_id,
        chunk_id=match.chunk_id,
        chunk_external_id=match.chunk_external_id,
        text=match.text,
        metadata=match.metadata,
        distance=match.distance,
        vector_score=match.score,
    )


def _candidate_from_full_text(
    match: VectorizedChunkFullTextSearchResult,
) -> _HybridCandidate:
    return _HybridCandidate(
        source=match.source,
        source_type=match.source_type,
        source_id=match.source_id,
        external_id=match.external_id,
        chunk_id=match.chunk_id,
        chunk_external_id=match.chunk_external_id,
        text=match.text,
        metadata=match.metadata,
        full_text_score=match.full_text_score,
    )


def _rrf(rank: int, k: int) -> float:
    return 1.0 / (k + rank)


def _best_rank(current: int | None, candidate: int) -> int:
    return candidate if current is None else min(current, candidate)


def _best_score(current: float | None, candidate: float) -> float:
    return candidate if current is None else max(current, candidate)


def _best_distance(current: float | None, candidate: float) -> float:
    return candidate if current is None else min(current, candidate)
