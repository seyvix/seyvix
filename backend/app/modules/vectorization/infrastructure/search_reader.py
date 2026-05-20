from __future__ import annotations

import re
from typing import Any
from typing import cast as typing_cast

from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
from sqlalchemy import DateTime, and_, cast, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.modules.vectorization.contracts import (
    VectorizedChunkFullTextSearchResult,
    VectorizedChunkSearchFilters,
    VectorizedChunkSearchResult,
)
from app.modules.vectorization.models import (
    VectorizationChunk,
    VectorizationEmbedding,
    VectorizationSource,
)

_REGCONFIG_RE = re.compile(r"^[A-Za-z0-9_]+$")


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
        source: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        filters: VectorizedChunkSearchFilters | None = None,
    ) -> list[VectorizedChunkSearchResult]:
        indexed_embedding = cast(VectorizationEmbedding.embedding, Vector(dimensions))
        distance = indexed_embedding.cosine_distance(query_embedding).label("distance")
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
            .where(
                *_filter_clauses(
                    source=source,
                    source_type=source_type,
                    source_id=source_id,
                    filters=filters,
                )
            )
            .order_by(distance.asc())
            .limit(limit)
        )
        rows = (await self.session.execute(query)).all()
        results: list[VectorizedChunkSearchResult] = []
        for chunk, source_record, raw_distance in rows:
            distance_value = float(raw_distance)
            results.append(
                VectorizedChunkSearchResult(
                    source=source_record.source,
                    source_type=source_record.source_type,
                    source_id=source_record.source_id,
                    external_id=source_record.external_id,
                    chunk_id=chunk.id,
                    chunk_external_id=chunk.chunk_external_id,
                    text=chunk.text,
                    metadata=chunk.metadata_,
                    distance=distance_value,
                    score=1.0 - distance_value,
                )
            )
        return results

    async def search_full_text_chunks(
        self,
        *,
        owner_user_id: str,
        query: str,
        limit: int,
        search_config: str,
        source: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        filters: VectorizedChunkSearchFilters | None = None,
    ) -> list[VectorizedChunkFullTextSearchResult]:
        config = _regconfig_literal(search_config)
        ts_query = func.websearch_to_tsquery(config, query)
        search_vector = func.to_tsvector(config, VectorizationChunk.text)
        full_text_score = func.ts_rank_cd(search_vector, ts_query).label(
            "full_text_score"
        )
        statement = (
            select(VectorizationChunk, VectorizationSource, full_text_score)
            .join(
                VectorizationSource,
                VectorizationSource.id == VectorizationChunk.source_record_id,
            )
            .where(
                VectorizationChunk.owner_user_id == owner_user_id,
                VectorizationSource.owner_user_id == owner_user_id,
                VectorizationSource.status == "synced",
                search_vector.op("@@")(ts_query),
            )
            .where(
                *_filter_clauses(
                    source=source,
                    source_type=source_type,
                    source_id=source_id,
                    filters=filters,
                )
            )
            .order_by(full_text_score.desc(), VectorizationChunk.created_at.desc())
            .limit(limit)
        )
        rows = (await self.session.execute(statement)).all()
        results: list[VectorizedChunkFullTextSearchResult] = []
        for chunk, source_record, raw_score in rows:
            results.append(
                VectorizedChunkFullTextSearchResult(
                    source=source_record.source,
                    source_type=source_record.source_type,
                    source_id=source_record.source_id,
                    external_id=source_record.external_id,
                    chunk_id=chunk.id,
                    chunk_external_id=chunk.chunk_external_id,
                    text=chunk.text,
                    metadata=chunk.metadata_,
                    full_text_score=float(raw_score),
                )
            )
        return results


def _filter_clauses(
    *,
    source: str | None,
    source_type: str | None,
    source_id: str | None,
    filters: VectorizedChunkSearchFilters | None,
) -> list[ColumnElement[bool]]:
    clauses: list[ColumnElement[bool]] = []
    if source is not None:
        clauses.append(VectorizationSource.source == source)
    if source_type is not None:
        clauses.append(VectorizationSource.source_type == source_type)
    if source_id is not None:
        clauses.append(VectorizationSource.source_id == source_id)
    if filters is None:
        return clauses

    if filters.source is not None:
        clauses.append(VectorizationSource.source == filters.source)
    if filters.source_type is not None:
        clauses.append(VectorizationSource.source_type == filters.source_type)
    if filters.source_id is not None:
        clauses.append(VectorizationSource.source_id == filters.source_id)
    if filters.content_types:
        clauses.append(
            or_(*[_content_type_clause(value) for value in filters.content_types])
        )
    if filters.content_source is not None:
        normalized_source = filters.content_source.casefold()
        clauses.append(
            or_(
                func.lower(_metadata_text("content_source_provider"))
                == normalized_source,
                func.lower(_metadata_text("source_provider")) == normalized_source,
            )
        )
    if filters.created_at_from is not None:
        clauses.append(
            _metadata_timestamp("content_created_at") >= filters.created_at_from
        )
    if filters.created_at_to is not None:
        clauses.append(
            _metadata_timestamp("content_created_at") <= filters.created_at_to
        )
    if filters.updated_at_from is not None:
        clauses.append(
            _metadata_timestamp("content_updated_at") >= filters.updated_at_from
        )
    if filters.updated_at_to is not None:
        clauses.append(
            _metadata_timestamp("content_updated_at") <= filters.updated_at_to
        )
    return clauses


def _content_type_clause(raw_value: str) -> ColumnElement[bool]:
    value = raw_value.strip().casefold()
    media_type = func.lower(_metadata_text("media_type"))
    mime_type = func.lower(func.coalesce(_metadata_text("mime_type"), ""))
    source_filename = func.lower(func.coalesce(_metadata_text("source_filename"), ""))
    if value in {"note", "notes"}:
        return media_type == "text"
    if value == "pdf":
        return and_(
            media_type == "document",
            or_(mime_type == "application/pdf", source_filename.like("%.pdf")),
        )
    return media_type == value


def _metadata_text(key: str) -> ColumnElement[str]:
    return typing_cast(ColumnElement[str], VectorizationChunk.metadata_[key].as_string())


def _metadata_timestamp(key: str) -> ColumnElement[Any]:
    return cast(_metadata_text(key), DateTime(timezone=True))


def _regconfig_literal(search_config: str) -> ColumnElement[Any]:
    if not _REGCONFIG_RE.fullmatch(search_config):
        raise ValueError("PostgreSQL full-text search config is invalid.")
    return literal_column(f"'{search_config}'")
