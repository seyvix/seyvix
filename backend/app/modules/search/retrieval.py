"""SQL retrievers. Each returns a ranked list; the service fuses them with weighted RRF.

- `fts_chunks`: GIN index on the generated `search_vector` column (same expression by
  construction), ranked by `ts_rank_cd` with length normalization.
- `vector_chunks`: owner-scoped cosine KNN. Owners with few embedded chunks get an exact scan
  (the `cosine_distance()` function form is never served by the index), which is 100% recall
  and cheap at that size. Larger owners use the global HNSW index with `ef_search` raised and
  pgvector >= 0.8 iterative scan, so owner/source filters applied during the scan cannot
  starve the result list (the classic post-filter recall loss of a shared ANN index).
- `metadata_notes` / `title_trigram_notes`: live note metadata (title, file names, tags,
  category) so freshly applied tags/categories are searchable without re-indexing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import HALFVEC  # type: ignore[import-untyped]
from sqlalchemy import (
    ColumnElement,
    Select,
    and_,
    any_,
    bindparam,
    func,
    literal_column,
    or_,
    select,
    union,
)
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Text

from app.core.config import Settings
from app.modules.content.models import ContentAsset, ContentObject
from app.modules.tags.models import ContentTagAssignment, Tag
from app.modules.taxonomy.models import TaxonomyContentAssignment
from app.modules.vectorization.documents import SOURCE_CONTENT
from app.modules.vectorization.models import (
    EMBEDDING_DIMENSIONS,
    FTS_CONFIG,
    VectorizationChunk,
    VectorizationSource,
)

_REGCONFIG: ColumnElement[Any] = literal_column(f"'{FTS_CONFIG}'::regconfig")
TRIGRAM_WORD_SIMILARITY = 0.45
METADATA_CANDIDATES = 500
ACCEPTED_TAG_STATUS = "accepted"


@dataclass(frozen=True, slots=True)
class ContentFilter:
    """Filters pushed down into retrieval for note search (Content re-applies all filters)."""

    content_types: tuple[str, ...] = ()
    is_favorite: bool | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    updated_from: datetime | None = None
    updated_to: datetime | None = None


@dataclass(frozen=True, slots=True)
class Scope:
    owner_user_id: str
    source: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    content: ContentFilter | None = None

    @property
    def is_content(self) -> bool:
        return (self.source, self.source_type) == SOURCE_CONTENT


@dataclass(frozen=True, slots=True)
class ChunkHit:
    source: str
    source_type: str
    source_id: str
    chunk_id: str
    chunk_index: int
    text: str
    score: float
    distance: float | None = None


@dataclass(slots=True)
class NoteMetadata:
    id: str
    title: str
    source_filename: str | None
    category_path: str | None
    category_name: str | None
    tag_names: list[str] = field(default_factory=list)
    tag_slugs: list[str] = field(default_factory=list)
    asset_filenames: list[str] = field(default_factory=list)

    def parts(self) -> list[tuple[str, float]]:
        parts: list[tuple[str, float]] = [(self.title, 8.0)]
        if self.source_filename:
            parts.append((self.source_filename, 4.0))
        if self.category_path:
            parts.append((self.category_path, 5.0))
        if self.category_name:
            parts.append((self.category_name, 5.0))
        parts.extend((name, 10.0) for name in self.tag_names)
        parts.extend((slug, 8.0) for slug in self.tag_slugs)
        parts.extend((filename, 4.0) for filename in self.asset_filenames if filename)
        return parts


# --- chunk retrievers --------------------------------------------------------------------
def _chunk_select(*columns: Any) -> Select[Any]:
    return select(
        VectorizationSource.source,
        VectorizationSource.source_type,
        VectorizationSource.source_id,
        VectorizationChunk.id,
        VectorizationChunk.chunk_index,
        VectorizationChunk.text,
        *columns,
    ).join(VectorizationSource, VectorizationSource.id == VectorizationChunk.source_record_id)


def _apply_scope(statement: Select[Any], scope: Scope) -> Select[Any]:
    statement = statement.where(VectorizationChunk.owner_user_id == scope.owner_user_id)
    if scope.source is not None:
        statement = statement.where(VectorizationSource.source == scope.source)
    if scope.source_type is not None:
        statement = statement.where(VectorizationSource.source_type == scope.source_type)
    if scope.source_id is not None:
        statement = statement.where(VectorizationSource.source_id == scope.source_id)
    if scope.is_content:
        statement = statement.join(
            ContentObject,
            and_(
                ContentObject.id == VectorizationSource.source_id,
                ContentObject.owner_user_id == scope.owner_user_id,
            ),
        ).where(*content_filter_clauses(scope.content))
    return statement


def tsquery(query: str, *, websearch: bool = False) -> ColumnElement[Any]:
    if websearch:
        return func.websearch_to_tsquery(_REGCONFIG, query)
    return func.to_tsquery(_REGCONFIG, query)


async def fts_chunks(
    session: AsyncSession, scope: Scope, ts_query: ColumnElement[Any], *, limit: int
) -> list[ChunkHit]:
    # Normalization 1: divide by 1 + log(length) so long chunks don't win on volume alone.
    rank = func.ts_rank_cd(VectorizationChunk.search_vector, ts_query, 1).label("rank")
    statement = _apply_scope(_chunk_select(rank), scope).where(
        VectorizationChunk.search_vector.op("@@")(ts_query)
    )
    rows = await session.execute(statement.order_by(rank.desc()).limit(limit))
    return [
        ChunkHit(
            source=row.source,
            source_type=row.source_type,
            source_id=row.source_id,
            chunk_id=row.id,
            chunk_index=row.chunk_index,
            text=row.text,
            score=float(row.rank),
        )
        for row in rows
    ]


async def vector_chunks(
    session: AsyncSession,
    scope: Scope,
    embedding: Sequence[float],
    *,
    settings: Settings,
    limit: int,
    exact: bool,
) -> list[ChunkHit]:
    """`exact` comes from `use_exact_vector_search` (decide once per request)."""
    query_vector = bindparam(
        "query_vector", value=list(embedding), type_=HALFVEC(EMBEDDING_DIMENSIONS)
    )
    distance: ColumnElement[Any]
    if exact:
        distance = func.cosine_distance(VectorizationChunk.embedding, query_vector)
    else:
        distance = VectorizationChunk.embedding.op("<=>")(query_vector)
        ef_search = str(max(settings.search_hnsw_ef_search, limit))
        await session.execute(select(func.set_config("hnsw.ef_search", ef_search, True)))
        await session.execute(select(func.set_config("hnsw.iterative_scan", "relaxed_order", True)))
    candidates = (
        (
            _apply_scope(_chunk_select(distance.label("distance")), scope)
            .where(
                VectorizationChunk.embedding.is_not(None),
                VectorizationSource.embedding_model == settings.ai_embedding_model,
            )
            .order_by(distance)
            .limit(limit)
        )
        .cte("vector_candidates")
        .prefix_with("MATERIALIZED")
    )
    # relaxed_order may return slightly out-of-order rows; re-sort the small candidate set.
    rows = await session.execute(select(candidates).order_by(candidates.c.distance))
    min_score = settings.search_semantic_min_score
    hits: list[ChunkHit] = []
    for row in rows:
        score = 1.0 - float(row.distance)
        if score < min_score:
            continue
        hits.append(
            ChunkHit(
                source=row.source,
                source_type=row.source_type,
                source_id=row.source_id,
                chunk_id=row.id,
                chunk_index=row.chunk_index,
                text=row.text,
                score=score,
                distance=float(row.distance),
            )
        )
    return hits


async def use_exact_vector_search(
    session: AsyncSession, owner_user_id: str, settings: Settings
) -> bool:
    """True when the owner's embedded chunk count is small enough for an exact scan.

    The count is bounded (LIMIT threshold + 1) so the check stays cheap for large owners.
    """
    threshold = settings.search_vector_exact_max_chunks
    bounded = (
        select(literal_column("1"))
        .where(
            VectorizationChunk.owner_user_id == owner_user_id,
            VectorizationChunk.embedding.is_not(None),
        )
        .limit(threshold + 1)
        .subquery()
    )
    count = int(await session.scalar(select(func.count()).select_from(bounded)) or 0)
    return count <= threshold


async def content_embedding_centroid(
    session: AsyncSession, *, owner_user_id: str, content_object_id: str, model: str
) -> list[float] | None:
    """Mean of a note's chunk embeddings, computed in SQL (`avg(halfvec)`)."""
    value = await session.scalar(
        select(func.avg(VectorizationChunk.embedding))
        .join(VectorizationSource, VectorizationSource.id == VectorizationChunk.source_record_id)
        .where(
            VectorizationSource.owner_user_id == owner_user_id,
            VectorizationSource.source == SOURCE_CONTENT[0],
            VectorizationSource.source_type == SOURCE_CONTENT[1],
            VectorizationSource.source_id == content_object_id,
            VectorizationSource.embedding_model == model,
            VectorizationChunk.embedding.is_not(None),
        )
    )
    if value is None:
        return None
    return [float(component) for component in _to_list(value)]


def _to_list(value: Any) -> list[float]:
    if hasattr(value, "to_list"):
        return list(value.to_list())
    return list(value)


# --- note (metadata) retrievers ----------------------------------------------------------
def content_filter_clauses(content: ContentFilter | None) -> list[ColumnElement[bool]]:
    clauses: list[ColumnElement[bool]] = [ContentObject.deleted_at.is_(None)]
    if content is None:
        return clauses
    if content.content_types:
        clauses.append(or_(*[_content_type_clause(value) for value in content.content_types]))
    if content.is_favorite is not None:
        clauses.append(ContentObject.is_favorite.is_(content.is_favorite))
    if content.created_from is not None:
        clauses.append(ContentObject.created_at >= content.created_from)
    if content.created_to is not None:
        clauses.append(ContentObject.created_at <= content.created_to)
    if content.updated_from is not None:
        clauses.append(ContentObject.updated_at >= content.updated_from)
    if content.updated_to is not None:
        clauses.append(ContentObject.updated_at <= content.updated_to)
    return clauses


def _content_type_clause(raw_value: str) -> ColumnElement[bool]:
    value = raw_value.strip().casefold()
    if value in {"note", "notes"}:
        return ContentObject.media_type == "text"
    if value == "pdf":
        return and_(
            ContentObject.media_type == "document",
            or_(
                func.lower(func.coalesce(ContentObject.mime_type, "")) == "application/pdf",
                func.lower(func.coalesce(ContentObject.source_filename, "")).like("%.pdf"),
            ),
        )
    return ContentObject.media_type == value


async def metadata_notes(
    session: AsyncSession,
    *,
    owner_user_id: str,
    variants: Sequence[str],
    content: ContentFilter | None,
) -> list[NoteMetadata]:
    """Notes whose title/file names/tags/category contain any variant (substring)."""
    if not variants:
        return []
    patterns = any_(array([f"%{variant}%" for variant in variants], type_=Text))

    def matches(column: Any) -> ColumnElement[bool]:
        clause: ColumnElement[bool] = column.op("ILIKE")(patterns)
        return clause

    matching_ids = union(
        select(ContentObject.id.label("id")).where(
            ContentObject.owner_user_id == owner_user_id,
            or_(matches(ContentObject.title), matches(ContentObject.source_filename)),
        ),
        select(ContentTagAssignment.content_object_id)
        .join(Tag, Tag.id == ContentTagAssignment.tag_id)
        .where(
            ContentTagAssignment.owner_user_id == owner_user_id,
            ContentTagAssignment.status == ACCEPTED_TAG_STATUS,
            or_(matches(Tag.name), matches(Tag.slug)),
        ),
        select(TaxonomyContentAssignment.content_object_id).where(
            TaxonomyContentAssignment.owner_user_id == owner_user_id,
            TaxonomyContentAssignment.is_current.is_(True),
            or_(
                matches(TaxonomyContentAssignment.category_path_snapshot),
                matches(TaxonomyContentAssignment.category_name_snapshot),
            ),
        ),
        select(ContentAsset.content_object_id)
        .join(ContentObject, ContentObject.id == ContentAsset.content_object_id)
        .where(ContentObject.owner_user_id == owner_user_id, matches(ContentAsset.filename)),
    ).subquery()

    statement = (
        select(
            ContentObject.id,
            ContentObject.title,
            ContentObject.source_filename,
            _current_category(TaxonomyContentAssignment.category_path_snapshot).label(
                "category_path"
            ),
            _current_category(TaxonomyContentAssignment.category_name_snapshot).label(
                "category_name"
            ),
            _accepted_tags(Tag.name).label("tag_names"),
            _accepted_tags(Tag.slug).label("tag_slugs"),
            select(func.array_agg(ContentAsset.filename))
            .where(ContentAsset.content_object_id == ContentObject.id)
            .correlate(ContentObject)
            .scalar_subquery()
            .label("asset_filenames"),
        )
        .where(
            ContentObject.id.in_(select(matching_ids.c.id)),
            ContentObject.owner_user_id == owner_user_id,
            *content_filter_clauses(content),
        )
        .order_by(ContentObject.created_at.desc())
        .limit(METADATA_CANDIDATES)
    )
    rows = await session.execute(statement)
    return [
        NoteMetadata(
            id=row.id,
            title=row.title or "",
            source_filename=row.source_filename,
            category_path=row.category_path,
            category_name=row.category_name,
            tag_names=list(row.tag_names or []),
            tag_slugs=list(row.tag_slugs or []),
            asset_filenames=list(row.asset_filenames or []),
        )
        for row in rows
    ]


def _current_category(column: Any) -> Any:
    return (
        select(column)
        .where(
            TaxonomyContentAssignment.content_object_id == ContentObject.id,
            TaxonomyContentAssignment.is_current.is_(True),
        )
        .correlate(ContentObject)
        .limit(1)
        .scalar_subquery()
    )


def _accepted_tags(column: Any) -> Any:
    return (
        select(func.array_agg(column))
        .join(ContentTagAssignment, ContentTagAssignment.tag_id == Tag.id)
        .where(
            ContentTagAssignment.content_object_id == ContentObject.id,
            ContentTagAssignment.status == ACCEPTED_TAG_STATUS,
        )
        .correlate(ContentObject)
        .scalar_subquery()
    )


async def title_trigram_notes(
    session: AsyncSession,
    *,
    owner_user_id: str,
    query: str,
    content: ContentFilter | None,
    limit: int,
) -> list[tuple[str, float]]:
    """Typo-tolerant title matches (pg_trgm word similarity), best first."""
    similarity = func.word_similarity(query, ContentObject.title).label("similarity")
    rows = await session.execute(
        select(ContentObject.id, similarity)
        .where(
            ContentObject.owner_user_id == owner_user_id,
            similarity >= TRIGRAM_WORD_SIMILARITY,
            *content_filter_clauses(content),
        )
        .order_by(similarity.desc(), ContentObject.created_at.desc())
        .limit(limit)
    )
    return [(row.id, float(row.similarity)) for row in rows]
