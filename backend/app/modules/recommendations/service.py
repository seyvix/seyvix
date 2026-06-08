from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.modules.content.infrastructure.repositories import ContentRepository
from app.modules.content.models import ContentObject
from app.modules.content.schemas import TagResponse
from app.modules.recommendations.infrastructure.repositories import (
    RecommendationRepository,
    SourceEmbedding,
)
from app.modules.recommendations.schemas import NoteRecommendationsResponse, RecommendedNoteItem
from app.modules.vectorization.contracts import (
    VectorizedChunkSearchReader,
    VectorizedChunkSearchResult,
    build_vectorized_chunk_search_reader,
)

MAX_NOTE_RECOMMENDATIONS = 5
_CANDIDATE_MULTIPLIER = 20
_MATCHED_TEXT_MAX_CHARS = 320


class RecommendationNoteNotFoundError(Exception):
    pass


@dataclass(slots=True)
class _RecommendationCandidate:
    content_object_id: str
    score: float
    distance: float
    matched_text: str
    match_count: int = 1


class RecommendationService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings | None = None,
        chunk_reader: VectorizedChunkSearchReader | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.content = ContentRepository(session)
        self.repository = RecommendationRepository(session)
        self.chunk_reader = chunk_reader or build_vectorized_chunk_search_reader(session)

    async def recommend_notes(
        self,
        *,
        owner_user_id: str,
        note_ref: str,
        limit: int,
    ) -> NoteRecommendationsResponse:
        target = await self._load_note(owner_user_id=owner_user_id, note_ref=note_ref)
        if target is None:
            raise RecommendationNoteNotFoundError

        effective_limit = _effective_limit(limit)
        query_embeddings = await self.repository.list_content_object_embeddings(
            owner_user_id=owner_user_id,
            content_object_id=target.id,
            provider=self.settings.vector_embedding_provider,
            model=self.settings.vector_embedding_model,
            dimensions=self.settings.vector_embedding_dimensions,
        )
        if not query_embeddings:
            return NoteRecommendationsResponse(items=[])

        query_embedding = _mean_embedding(query_embeddings)
        matches = await self.chunk_reader.search_similar_chunks(
            owner_user_id=owner_user_id,
            query_embedding=query_embedding,
            provider=self.settings.vector_embedding_provider,
            model=self.settings.vector_embedding_model,
            dimensions=self.settings.vector_embedding_dimensions,
            limit=max(effective_limit * _CANDIDATE_MULTIPLIER, effective_limit + 5),
            source="content",
            source_type="content_object",
        )
        candidates = _aggregate_matches(matches=matches, target_id=target.id)
        object_ids = [candidate.content_object_id for candidate in candidates]
        objects_by_id = await self.repository.list_recommendable_content_objects(
            owner_user_id=owner_user_id,
            content_object_ids=object_ids,
        )

        items: list[RecommendedNoteItem] = []
        for candidate in candidates:
            content_object = objects_by_id.get(candidate.content_object_id)
            if content_object is None:
                continue
            items.append(_item_from_candidate(candidate, content_object))
            if len(items) >= effective_limit:
                break
        return NoteRecommendationsResponse(items=items)

    async def _load_note(self, *, owner_user_id: str, note_ref: str) -> ContentObject | None:
        normalized_ref = note_ref.strip()
        object_id = _uuid_ref(normalized_ref)
        if object_id is not None:
            content_object = await self.content.get_by_id(
                owner_user_id=owner_user_id,
                object_id=object_id,
            )
            if content_object is not None:
                return content_object
        return await self.content.get_by_slug(owner_user_id=owner_user_id, slug=normalized_ref)


def _effective_limit(limit: int) -> int:
    return min(max(limit, 1), MAX_NOTE_RECOMMENDATIONS)


def _uuid_ref(value: str) -> str | None:
    try:
        return str(UUID(value))
    except ValueError:
        return None


def _mean_embedding(embeddings: list[SourceEmbedding]) -> list[float]:
    dimensions = len(embeddings[0].vector)
    sums = [0.0] * dimensions
    for embedding in embeddings:
        for index, value in enumerate(embedding.vector):
            sums[index] += value
    count = float(len(embeddings))
    return [value / count for value in sums]


def _aggregate_matches(
    *,
    matches: list[VectorizedChunkSearchResult],
    target_id: str,
) -> list[_RecommendationCandidate]:
    candidates: dict[str, _RecommendationCandidate] = {}
    for match in matches:
        if match.source_id == target_id:
            continue
        existing = candidates.get(match.source_id)
        if existing is None:
            candidates[match.source_id] = _RecommendationCandidate(
                content_object_id=match.source_id,
                score=match.score,
                distance=match.distance,
                matched_text=_compact_text(match.text),
            )
            continue
        existing.match_count += 1
        if match.score > existing.score:
            existing.score = match.score
            existing.distance = match.distance
            existing.matched_text = _compact_text(match.text)
    return sorted(
        candidates.values(),
        key=lambda item: (item.score, item.match_count, -item.distance),
        reverse=True,
    )


def _item_from_candidate(
    candidate: _RecommendationCandidate,
    content_object: ContentObject,
) -> RecommendedNoteItem:
    return RecommendedNoteItem(
        id=content_object.id,
        slug=content_object.slug,
        kind=content_object.kind,
        media_type=content_object.media_type,
        title=content_object.title,
        score=_bounded_score(candidate.score),
        matched_text=candidate.matched_text,
        tags=[
            TagResponse(id=tag.id, name=tag.name, slug=tag.slug)
            for tag in sorted(content_object.tags, key=lambda item: item.name.casefold())
        ],
        created_at=content_object.created_at,
        updated_at=content_object.updated_at,
    )


def _bounded_score(score: float) -> float:
    return min(max(score, 0.0), 1.0)


def _compact_text(text: str) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= _MATCHED_TEXT_MAX_CHARS:
        return normalized
    return f"{normalized[: _MATCHED_TEXT_MAX_CHARS - 3].rstrip()}..."
