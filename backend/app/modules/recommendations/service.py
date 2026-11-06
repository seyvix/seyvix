"""Related notes: nearest neighbours of a note's embedding centroid (computed in SQL).

Without embeddings (AI disabled or not embedded yet) notes sharing the most accepted tags are
recommended instead, so the panel still works.
"""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import Settings, get_settings
from app.modules.content.models import ContentObject
from app.modules.content.schemas import TagResponse
from app.modules.recommendations.schemas import NoteRecommendationsResponse, RecommendedNoteItem
from app.modules.search.retrieval import (
    ChunkHit,
    Scope,
    content_embedding_centroid,
    use_exact_vector_search,
    vector_chunks,
)
from app.modules.tags.models import ContentTagAssignment, Tag
from app.modules.vectorization.documents import SOURCE_CONTENT

MAX_NOTE_RECOMMENDATIONS = 5
_CANDIDATE_CHUNKS = 100
_MATCHED_TEXT_MAX_CHARS = 320
_ACCEPTED = "accepted"


class RecommendationNoteNotFoundError(Exception):
    pass


class RecommendationService:
    def __init__(self, session: AsyncSession, *, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    async def recommend_notes(
        self, *, owner_user_id: str, note_ref: str, limit: int
    ) -> NoteRecommendationsResponse:
        target_id = await self._resolve_note_id(owner_user_id=owner_user_id, note_ref=note_ref)
        if target_id is None:
            raise RecommendationNoteNotFoundError
        effective_limit = min(max(limit, 1), MAX_NOTE_RECOMMENDATIONS)

        ranked = await self._semantic_candidates(owner_user_id, target_id)
        if not ranked:
            ranked = await self._shared_tag_candidates(owner_user_id, target_id)
        if not ranked:
            return NoteRecommendationsResponse(items=[])

        objects = {
            item.id: item
            for item in await self.session.scalars(
                select(ContentObject).where(
                    ContentObject.owner_user_id == owner_user_id,
                    ContentObject.id.in_([note_id for note_id, _, _ in ranked]),
                    ContentObject.deleted_at.is_(None),
                )
            )
        }
        kept = [entry for entry in ranked if entry[0] in objects][:effective_limit]
        tags = await self._tags_for([note_id for note_id, _, _ in kept])
        return NoteRecommendationsResponse(
            items=[
                RecommendedNoteItem(
                    id=objects[note_id].id,
                    slug=objects[note_id].slug,
                    kind=objects[note_id].kind,
                    media_type=objects[note_id].media_type,
                    title=objects[note_id].title,
                    score=min(max(score, 0.0), 1.0),
                    matched_text=matched_text,
                    tags=tags.get(note_id, []),
                    created_at=objects[note_id].created_at,
                    updated_at=objects[note_id].updated_at,
                )
                for note_id, score, matched_text in kept
            ]
        )

    async def _resolve_note_id(self, *, owner_user_id: str, note_ref: str) -> str | None:
        ref = note_ref.strip()
        try:
            object_id: str | None = str(UUID(ref))
        except ValueError:
            object_id = None
        condition = (
            or_(ContentObject.id == object_id, ContentObject.slug == ref)
            if object_id
            else ContentObject.slug == ref
        )
        note_id: str | None = await self.session.scalar(
            select(ContentObject.id)
            .where(
                ContentObject.owner_user_id == owner_user_id,
                ContentObject.deleted_at.is_(None),
                condition,
            )
            .order_by((ContentObject.id == (object_id or "")).desc())
            .limit(1)
        )
        return note_id

    async def _semantic_candidates(
        self, owner_user_id: str, target_id: str
    ) -> list[tuple[str, float, str]]:
        centroid = await content_embedding_centroid(
            self.session,
            owner_user_id=owner_user_id,
            content_object_id=target_id,
            model=self.settings.ai_embedding_model,
        )
        if centroid is None:
            return []
        scope = Scope(
            owner_user_id=owner_user_id, source=SOURCE_CONTENT[0], source_type=SOURCE_CONTENT[1]
        )
        hits = await vector_chunks(
            self.session,
            scope,
            centroid,
            settings=self.settings,
            limit=_CANDIDATE_CHUNKS,
            exact=await use_exact_vector_search(self.session, owner_user_id, self.settings),
        )
        best: dict[str, ChunkHit] = {}
        counts: dict[str, int] = defaultdict(int)
        for hit in hits:  # hits are ordered best first
            if hit.source_id == target_id:
                continue
            counts[hit.source_id] += 1
            best.setdefault(hit.source_id, hit)
        ordered = sorted(
            best.values(), key=lambda hit: (hit.score, counts[hit.source_id]), reverse=True
        )
        return [(hit.source_id, hit.score, _compact_text(hit.text)) for hit in ordered]

    async def _shared_tag_candidates(
        self, owner_user_id: str, target_id: str
    ) -> list[tuple[str, float, str]]:
        mine = aliased(ContentTagAssignment)
        other = aliased(ContentTagAssignment)
        target_tags = await self.session.scalar(
            select(func.count()).where(
                mine.content_object_id == target_id, mine.status == _ACCEPTED
            )
        )
        if not target_tags:
            return []
        shared = func.count().label("shared")
        rows = await self.session.execute(
            select(other.content_object_id, shared)
            .join(mine, and_(mine.tag_id == other.tag_id, mine.status == _ACCEPTED))
            .where(
                mine.content_object_id == target_id,
                other.owner_user_id == owner_user_id,
                other.status == _ACCEPTED,
                other.content_object_id != target_id,
            )
            .group_by(other.content_object_id)
            .order_by(shared.desc())
            .limit(MAX_NOTE_RECOMMENDATIONS * 4)
        )
        return [(row.content_object_id, row.shared / target_tags, "") for row in rows]

    async def _tags_for(self, note_ids: list[str]) -> dict[str, list[TagResponse]]:
        if not note_ids:
            return {}
        rows = await self.session.execute(
            select(ContentTagAssignment.content_object_id, Tag.id, Tag.name, Tag.slug)
            .join(Tag, Tag.id == ContentTagAssignment.tag_id)
            .where(
                ContentTagAssignment.content_object_id.in_(note_ids),
                ContentTagAssignment.status == _ACCEPTED,
            )
            .order_by(func.lower(Tag.name))
        )
        result: dict[str, list[TagResponse]] = defaultdict(list)
        for row in rows:
            result[row.content_object_id].append(
                TagResponse(id=row.id, name=row.name, slug=row.slug)
            )
        return result


def _compact_text(text: str) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= _MATCHED_TEXT_MAX_CHARS:
        return normalized
    return f"{normalized[: _MATCHED_TEXT_MAX_CHARS - 3].rstrip()}..."
