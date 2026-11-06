"""One search path: Postgres FTS (+ live metadata, + trigram typo fallback) and, when AI is
available, pgvector — fused with weighted Reciprocal Rank Fusion.

AI on the request path is strictly bounded: query embedding / expansion run concurrently with
the lexical SQL under `search_ai_timeout_seconds`, results are cached per process, and a
failure opens a short circuit breaker. Any AI problem silently degrades to lexical search.
"""

from __future__ import annotations

import asyncio
import time
from array import array
from collections import OrderedDict, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.modules.content.models import ContentObject
from app.modules.llm.client import AIClient, AIError, get_ai_client
from app.modules.search.retrieval import (
    ChunkHit,
    ContentFilter,
    Scope,
    fts_chunks,
    metadata_notes,
    title_trigram_notes,
    tsquery,
    use_exact_vector_search,
    vector_chunks,
)
from app.modules.search.schemas import (
    HybridSearchResponse,
    HybridSearchResult,
    SearchCapabilitiesResponse,
    SearchContentMatch,
    SearchFilters,
    SearchMode,
    SemanticSearchResult,
)
from app.modules.search.terms import (
    ParsedQuery,
    highlight_ranges,
    highlight_terms,
    metadata_score,
    metadata_term_groups,
)
from app.modules.vectorization.documents import SOURCE_CONTENT

logger = get_logger(__name__)

MAX_MATCHES_PER_NOTE: Final = 2
MAX_CHUNK_CANDIDATES: Final = 400
MAX_VECTOR_CANDIDATES: Final = 200
TRIGRAM_MIN_QUERY_CHARS: Final = 4
TRIGRAM_WHEN_FEWER_NOTES: Final = 10
TRIGRAM_LIMIT: Final = 50
BREAKER_SECONDS: Final = 30.0
CACHE_SIZE: Final = 256

# Weighted RRF: primary retrievers 1.0, recall-oriented helpers lower.
W_STRICT: Final = 1.0
W_LOOSE: Final = 0.5
W_METADATA: Final = 1.0
W_TRIGRAM: Final = 0.4
W_VECTOR: Final = 1.0
W_EXPANSION: Final = 0.5


class SearchValidationError(Exception):
    """Empty/invalid query (422)."""


class SearchUnavailableError(Exception):
    """Explicit semantic search requested but AI is disabled or unavailable (503)."""


class _Expansion(BaseModel):
    queries: list[str] = Field(default_factory=list, max_length=5)


class _RequestAI:
    """Process-wide request-path AI helper: LRU caches + circuit breaker."""

    def __init__(self) -> None:
        self._vectors: OrderedDict[tuple[str, str], array[float]] = OrderedDict()
        self._expansions: OrderedDict[tuple[str, str], tuple[str, ...]] = OrderedDict()
        self._open_until = 0.0

    @property
    def available(self) -> bool:
        return time.monotonic() >= self._open_until

    def trip(self, reason: str) -> None:
        self._open_until = time.monotonic() + BREAKER_SECONDS
        logger.warning("search.ai.degraded", reason=reason, retry_in_seconds=BREAKER_SECONDS)

    async def embed(self, client: AIClient, texts: Sequence[str]) -> list[list[float]]:
        """Embeds search queries (cached per process)."""
        model = client.embedding_model(query=True)
        missing = [text for text in dict.fromkeys(texts) if (model, text) not in self._vectors]
        if missing:
            vectors = await client.embed(missing, query=True)
            for text, vector in zip(missing, vectors, strict=True):
                _remember(self._vectors, (model, text), array("f", vector))
        result: list[list[float]] = []
        for text in texts:
            self._vectors.move_to_end((model, text))
            result.append(self._vectors[(model, text)].tolist())
        return result

    async def expand(self, client: AIClient, query: str, max_queries: int) -> list[str]:
        key = (client.settings.ai_chat_model, query)
        cached = self._expansions.get(key)
        if cached is None:
            expansion = await client.chat_json(
                [
                    {
                        "role": "system",
                        "content": (
                            "You rewrite search queries for a personal notes search engine. "
                            "Return up to "
                            f"{max_queries - 1} short alternative queries (synonyms, the other "
                            "language among English/Russian, expanded abbreviations) that keep "
                            'the intent. JSON: {"queries": ["..."]}'
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                _Expansion,
                temperature=0.2,
                max_tokens=200,
            )
            cached = tuple(expansion.queries)
            _remember(self._expansions, key, cached)
        return _dedupe_queries(query, cached, max_queries=max_queries)


_REQUEST_AI = _RequestAI()


@dataclass(slots=True)
class _Ranked:
    weight: float
    kind: str  # "fts" | "vector" | "metadata" | "trigram"
    chunks: list[ChunkHit] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _Retrieval:
    queries: list[str]
    lists: list[_Ranked]


class SearchService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings | None = None,
        ai_client: AIClient | None = None,
        use_ai: bool = True,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.ai = ai_client or (get_ai_client(self.settings) if use_ai else None)

    # --- capabilities / modes --------------------------------------------------------------
    def resolve_mode(self, requested: SearchMode) -> SearchMode:
        return requested if self.ai is not None else "full_text"

    async def capabilities(self, *, owner_user_id: str) -> SearchCapabilitiesResponse:
        note_count = int(
            await self.session.scalar(
                select(func.count())
                .select_from(ContentObject)
                .where(
                    ContentObject.owner_user_id == owner_user_id,
                    ContentObject.deleted_at.is_(None),
                )
            )
            or 0
        )
        ai_enabled = self.ai is not None
        unlocked: list[SearchMode] = (
            ["full_text", "semantic", "hybrid"] if ai_enabled else ["full_text"]
        )
        return SearchCapabilitiesResponse(
            note_count=note_count,
            threshold=0,
            unlocked_modes=unlocked,
            default_mode="hybrid" if ai_enabled else "full_text",
            ai_enabled=ai_enabled,
        )

    # --- note search (GET /notes?search=) -------------------------------------------------
    async def search_content_object_matches(
        self,
        *,
        owner_user_id: str,
        query: str,
        limit: int = 500,
        mode: SearchMode,
        filters: SearchFilters | None = None,
    ) -> dict[str, list[SearchContentMatch]]:
        """Matching note ids, best first, with up to two matching chunks each."""
        normalized = _normalize_query(query)
        scope = Scope(
            owner_user_id=owner_user_id,
            source=SOURCE_CONTENT[0],
            source_type=SOURCE_CONTENT[1],
            content=_content_filter(filters),
        )
        retrieval = await self._retrieve(
            scope,
            normalized,
            mode=self.resolve_mode(mode),
            limit=limit,
            expand=self.settings.ai_query_expansion_enabled,
        )
        return _fuse_notes(retrieval.lists, normalized, k=self.settings.search_rrf_k, limit=limit)

    # --- generic chunk search (REST /search/*) --------------------------------------------
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
        normalized = _normalize_query(query)
        scope = _scope(owner_user_id, source, source_type, source_id, filters)
        expand = (
            expand_query if expand_query is not None else self.settings.ai_query_expansion_enabled
        )
        retrieval = await self._retrieve(
            scope,
            normalized,
            mode=self.resolve_mode(mode),
            limit=limit,
            expand=expand,
            chunk_only=True,
        )
        return HybridSearchResponse(
            query=normalized,
            expanded_queries=retrieval.queries,
            results=_fuse_chunks(retrieval.lists, k=self.settings.search_rrf_k)[:limit],
        )

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
        normalized = _normalize_query(query)
        if self.ai is None:
            raise SearchUnavailableError("AI is disabled.")
        try:
            vectors = await asyncio.wait_for(
                _REQUEST_AI.embed(self.ai, [normalized]),
                timeout=self.settings.search_ai_timeout_seconds,
            )
        except (AIError, TimeoutError) as exc:
            _REQUEST_AI.trip(type(exc).__name__)
            raise SearchUnavailableError("Embedding provider is unavailable.") from exc
        scope = _scope(owner_user_id, source, source_type, source_id, filters)
        hits = await vector_chunks(
            self.session,
            scope,
            vectors[0],
            settings=self.settings,
            limit=limit,
            exact=await use_exact_vector_search(self.session, owner_user_id, self.settings),
        )
        return [
            SemanticSearchResult(
                source=hit.source,
                source_type=hit.source_type,
                source_id=hit.source_id,
                external_id=_external_id(hit),
                chunk_id=hit.chunk_id,
                chunk_external_id=_chunk_external_id(hit),
                text=hit.text,
                metadata={},
                distance=hit.distance if hit.distance is not None else 1.0 - hit.score,
                score=hit.score,
            )
            for hit in hits
        ]

    # --- retrieval -------------------------------------------------------------------------
    async def _retrieve(
        self,
        scope: Scope,
        query: str,
        *,
        mode: SearchMode,
        limit: int,
        expand: bool,
        chunk_only: bool = False,
    ) -> _Retrieval:
        chunk_limit = min(max(limit, 20) * 2, MAX_CHUNK_CANDIDATES)
        ai_task: asyncio.Task[tuple[list[str], list[list[float]]]] | None = None
        if mode != "full_text" and self.ai is not None and _REQUEST_AI.available:
            ai_task = asyncio.create_task(self._query_vectors(self.ai, query, expand=expand))
        lists: list[_Ranked] = []
        queries = [query]
        try:
            if mode != "semantic":
                lists.extend(await self._lexical(scope, query, chunk_limit, chunk_only=chunk_only))
            if ai_task is not None:
                vectors: list[list[float]] = []
                try:
                    queries, vectors = await asyncio.wait_for(
                        ai_task, timeout=self.settings.search_ai_timeout_seconds
                    )
                except (AIError, TimeoutError) as exc:
                    _REQUEST_AI.trip(f"{type(exc).__name__}: {exc}")
                if vectors:
                    lists.extend(await self._semantic(scope, vectors, chunk_limit))
                if mode != "semantic":
                    for variant in queries[1:]:
                        variant_query = ParsedQuery.parse(variant).strict_tsquery()
                        if variant_query is not None:
                            hits = await fts_chunks(
                                self.session, scope, tsquery(variant_query), limit=chunk_limit
                            )
                            lists.append(_Ranked(W_EXPANSION, "fts", chunks=hits))
        finally:
            if ai_task is not None and not ai_task.done():
                ai_task.cancel()
        if mode == "semantic" and not any(item.kind == "vector" for item in lists):
            # Semantic requested but AI is unavailable: degrade to lexical search.
            lists.extend(await self._lexical(scope, query, chunk_limit, chunk_only=chunk_only))
        return _Retrieval(queries=queries, lists=lists)

    async def _query_vectors(
        self, client: AIClient, query: str, *, expand: bool
    ) -> tuple[list[str], list[list[float]]]:
        queries = [query]
        max_queries = self.settings.search_query_expansion_max_queries
        if expand and max_queries > 1:
            try:
                queries = await _REQUEST_AI.expand(client, query, max_queries)
            except AIError as exc:
                logger.info("search.expansion.skipped", error=str(exc))
        return queries, await _REQUEST_AI.embed(client, queries)

    async def _lexical(
        self, scope: Scope, query: str, chunk_limit: int, *, chunk_only: bool
    ) -> list[_Ranked]:
        parsed = ParsedQuery.parse(query)
        lists: list[_Ranked] = []
        strict = (
            tsquery(query, websearch=True)
            if parsed.websearch
            else (tsquery(text) if (text := parsed.strict_tsquery()) else None)
        )
        if strict is not None:
            hits = await fts_chunks(self.session, scope, strict, limit=chunk_limit)
            lists.append(_Ranked(W_STRICT, "fts", chunks=hits))
        loose = None if parsed.websearch else parsed.loose_tsquery()
        if loose is not None:
            hits = await fts_chunks(self.session, scope, tsquery(loose), limit=chunk_limit)
            lists.append(_Ranked(W_LOOSE, "fts", chunks=hits))
        if chunk_only or not scope.is_content:
            return lists

        groups = metadata_term_groups(query)
        variants = list(dict.fromkeys(v for group in groups for v in group.variants))
        candidates = await metadata_notes(
            self.session,
            owner_user_id=scope.owner_user_id,
            variants=variants,
            content=scope.content,
        )
        scored = [
            (score, note.id)
            for note in candidates
            if (score := metadata_score(query, groups, note.parts())) > 0
        ]
        scored.sort(key=lambda item: item[0], reverse=True)
        if scored:
            lists.append(_Ranked(W_METADATA, "metadata", notes=[note_id for _, note_id in scored]))

        found = {hit.source_id for item in lists for hit in item.chunks}
        found.update(note_id for _, note_id in scored)
        if len(query) >= TRIGRAM_MIN_QUERY_CHARS and len(found) < TRIGRAM_WHEN_FEWER_NOTES:
            similar = await title_trigram_notes(
                self.session,
                owner_user_id=scope.owner_user_id,
                query=query,
                content=scope.content,
                limit=TRIGRAM_LIMIT,
            )
            if similar:
                lists.append(
                    _Ranked(W_TRIGRAM, "trigram", notes=[note_id for note_id, _ in similar])
                )
        return lists

    async def _semantic(
        self, scope: Scope, vectors: list[list[float]], chunk_limit: int
    ) -> list[_Ranked]:
        exact = await use_exact_vector_search(self.session, scope.owner_user_id, self.settings)
        lists: list[_Ranked] = []
        for index, vector in enumerate(vectors):
            hits = await vector_chunks(
                self.session,
                scope,
                vector,
                settings=self.settings,
                limit=min(chunk_limit, MAX_VECTOR_CANDIDATES),
                exact=exact,
            )
            lists.append(_Ranked(W_VECTOR if index == 0 else W_EXPANSION, "vector", chunks=hits))
        return lists


# --- fusion ------------------------------------------------------------------------------
def _fuse_notes(
    lists: list[_Ranked], query: str, *, k: int, limit: int
) -> dict[str, list[SearchContentMatch]]:
    note_scores: dict[str, float] = defaultdict(float)
    chunk_scores: dict[str, float] = defaultdict(float)
    chunks: dict[str, ChunkHit] = {}
    for ranked in lists:
        if ranked.notes:
            for rank, note_id in enumerate(ranked.notes, start=1):
                note_scores[note_id] += ranked.weight / (k + rank)
            continue
        note_rank: dict[str, int] = {}
        for rank, hit in enumerate(ranked.chunks, start=1):
            chunk_scores[hit.chunk_id] += ranked.weight / (k + rank)
            chunks.setdefault(hit.chunk_id, hit)
            note_rank.setdefault(hit.source_id, len(note_rank) + 1)
        for note_id, rank in note_rank.items():
            note_scores[note_id] += ranked.weight / (k + rank)

    chunks_by_note: dict[str, list[ChunkHit]] = defaultdict(list)
    for hit in chunks.values():
        chunks_by_note[hit.source_id].append(hit)
    best_chunk = {
        note_id: max(chunk_scores[hit.chunk_id] for hit in hits)
        for note_id, hits in chunks_by_note.items()
    }
    ordered = sorted(
        note_scores,
        key=lambda note_id: (note_scores[note_id], best_chunk.get(note_id, 0.0)),
        reverse=True,
    )[:limit]
    terms = highlight_terms(query)
    result: dict[str, list[SearchContentMatch]] = {}
    for note_id in ordered:
        top = sorted(
            chunks_by_note.get(note_id, []),
            key=lambda hit: chunk_scores[hit.chunk_id],
            reverse=True,
        )[:MAX_MATCHES_PER_NOTE]
        result[note_id] = [
            SearchContentMatch(
                chunk_id=hit.chunk_id,
                chunk_external_id=_chunk_external_id(hit),
                text=hit.text.strip(),
                score=chunk_scores[hit.chunk_id],
                highlight_ranges=highlight_ranges(hit.text.strip(), terms),
            )
            for hit in top
        ]
    return result


@dataclass(slots=True)
class _FusedChunk:
    hit: ChunkHit
    score: float = 0.0
    vector_score: float | None = None
    full_text_score: float | None = None
    distance: float | None = None
    vector_rank: int | None = None
    full_text_rank: int | None = None


def _fuse_chunks(lists: list[_Ranked], *, k: int) -> list[HybridSearchResult]:
    fused: dict[str, _FusedChunk] = {}
    for ranked in lists:
        for rank, hit in enumerate(ranked.chunks, start=1):
            item = fused.setdefault(hit.chunk_id, _FusedChunk(hit=hit))
            item.score += ranked.weight / (k + rank)
            if ranked.kind == "vector":
                item.vector_rank = min(item.vector_rank or rank, rank)
                item.vector_score = max(item.vector_score or hit.score, hit.score)
                if hit.distance is not None:
                    item.distance = min(item.distance or hit.distance, hit.distance)
            else:
                item.full_text_rank = min(item.full_text_rank or rank, rank)
                item.full_text_score = max(item.full_text_score or hit.score, hit.score)
    ordered = sorted(fused.values(), key=lambda item: item.score, reverse=True)
    return [
        HybridSearchResult(
            source=item.hit.source,
            source_type=item.hit.source_type,
            source_id=item.hit.source_id,
            external_id=_external_id(item.hit),
            chunk_id=item.hit.chunk_id,
            chunk_external_id=_chunk_external_id(item.hit),
            text=item.hit.text,
            metadata={},
            distance=item.distance,
            score=item.score,
            vector_score=item.vector_score,
            full_text_score=item.full_text_score,
            vector_rank=item.vector_rank,
            full_text_rank=item.full_text_rank,
        )
        for item in ordered
    ]


# --- helpers -----------------------------------------------------------------------------
def _normalize_query(query: str) -> str:
    normalized = " ".join(query.split())
    if not normalized:
        raise SearchValidationError("Search query must not be empty.")
    return normalized[:512]


def _content_filter(filters: SearchFilters | None) -> ContentFilter | None:
    if filters is None:
        return None
    content_types = [value.strip() for value in filters.content_types if value.strip()]
    if filters.content_type and filters.content_type.strip():
        content_types.append(filters.content_type.strip())
    return ContentFilter(
        content_types=tuple(content_types),
        is_favorite=filters.is_favorite,
        created_from=filters.created_at_from or filters.date_from,
        created_to=filters.created_at_to or filters.date_to,
        updated_from=filters.updated_at_from,
        updated_to=filters.updated_at_to,
    )


def _scope(
    owner_user_id: str,
    source: str | None,
    source_type: str | None,
    source_id: str | None,
    filters: SearchFilters | None,
) -> Scope:
    if filters is not None:
        source = filters.source or source
        source_type = filters.source_type or source_type
        source_id = filters.source_id or source_id
    content = _content_filter(filters) if (source, source_type) == SOURCE_CONTENT else None
    return Scope(
        owner_user_id=owner_user_id,
        source=source,
        source_type=source_type,
        source_id=source_id,
        content=content,
    )


def _external_id(hit: ChunkHit) -> str:
    return f"{hit.source_type}:{hit.source_id}"


def _chunk_external_id(hit: ChunkHit) -> str:
    return f"{hit.source_type}:{hit.source_id}:chunk:{hit.chunk_index}"


def _dedupe_queries(query: str, candidates: Sequence[str], *, max_queries: int) -> list[str]:
    queries = [query]
    seen = {query.casefold()}
    for candidate in candidates:
        cleaned = " ".join(candidate.split())[:512]
        if cleaned and cleaned.casefold() not in seen:
            seen.add(cleaned.casefold())
            queries.append(cleaned)
        if len(queries) >= max_queries:
            break
    return queries


def _remember[K, V](cache: OrderedDict[K, V], key: K, value: V) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > CACHE_SIZE:
        cache.popitem(last=False)
