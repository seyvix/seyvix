"""Public vectorization API for other modules. Nothing here commits: callers own the transaction."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from pgvector.sqlalchemy import HALFVEC  # type: ignore[import-untyped]
from sqlalchemy import bindparam, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.vectorization.models import (
    EMBEDDING_DIMENSIONS,
    VectorizationChunk,
    VectorizationJob,
    VectorizationSource,
)
from app.platform.jobs import JOB_ACTIVE_STATUSES, JOB_CANCELLED, JOB_PENDING, utcnow


@dataclass(frozen=True, slots=True)
class SourceVectorMatch:
    source_id: str
    chunk_id: str
    score: float  # cosine similarity clamped to [0, 1]


async def enqueue_vectorization(
    session: AsyncSession,
    *,
    owner_user_id: str,
    source: str,
    source_type: str,
    source_id: str,
    priority: int = 100,
) -> None:
    """Queue (re)indexing. Idempotent: one job row per item; a finished job is reset and an
    in-flight one restarted (its stale result is discarded at finalize)."""
    now = utcnow()
    statement = pg_insert(VectorizationJob).values(
        id=str(uuid4()),
        owner_user_id=owner_user_id,
        source=source,
        source_type=source_type,
        source_id=source_id,
        status=JOB_PENDING,
        priority=priority,
        attempts=0,
        run_after=now,
        created_at=now,
        updated_at=now,
    )
    statement = statement.on_conflict_do_update(
        constraint="uq_vectorization_jobs_scope",
        set_={
            "status": JOB_PENDING,
            "attempts": 0,
            "run_after": now,
            "locked_at": None,
            "locked_by": None,
            "last_error": None,
            "priority": func.greatest(VectorizationJob.priority, statement.excluded.priority),
            "updated_at": now,
        },
    )
    await session.execute(statement)


async def delete_source_vectors(
    session: AsyncSession,
    *,
    owner_user_id: str,
    source: str,
    source_type: str,
    source_id: str,
) -> None:
    """Remove an item from the index (chunks cascade) and cancel its pending/running job."""
    await session.execute(
        delete(VectorizationSource).where(
            VectorizationSource.owner_user_id == owner_user_id,
            VectorizationSource.source == source,
            VectorizationSource.source_type == source_type,
            VectorizationSource.source_id == source_id,
        )
    )
    await session.execute(
        update(VectorizationJob)
        .where(
            VectorizationJob.owner_user_id == owner_user_id,
            VectorizationJob.source == source,
            VectorizationJob.source_type == source_type,
            VectorizationJob.source_id == source_id,
            VectorizationJob.status.in_(JOB_ACTIVE_STATUSES),
        )
        .values(status=JOB_CANCELLED, locked_at=None, locked_by=None, updated_at=utcnow())
    )


async def search_source_vectors(
    session: AsyncSession,
    *,
    owner_user_id: str,
    source: str,
    source_type: str,
    embedding: list[float],
    limit: int,
) -> list[SourceVectorMatch]:
    """Exact nearest items of one source type (best chunk per item), best first.

    Meant for small per-owner sets (e.g. taxonomy category profiles): exact distance via the
    owner/source filter, never the global HNSW index, so recall is 100%.
    """
    if len(embedding) != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Query embedding has {len(embedding)} dimensions, expected {EMBEDDING_DIMENSIONS}."
        )
    query_vector = bindparam("query_vector", value=embedding, type_=HALFVEC(EMBEDDING_DIMENSIONS))
    distance = func.cosine_distance(VectorizationChunk.embedding, query_vector)
    best_per_source = (
        select(
            VectorizationSource.source_id.label("source_id"),
            VectorizationChunk.id.label("chunk_id"),
            distance.label("distance"),
        )
        .join(VectorizationSource, VectorizationSource.id == VectorizationChunk.source_record_id)
        .where(
            VectorizationSource.owner_user_id == owner_user_id,
            VectorizationSource.source == source,
            VectorizationSource.source_type == source_type,
            VectorizationSource.embedding_model == get_settings().ai_embedding_model,
            VectorizationChunk.embedding.is_not(None),
        )
        .distinct(VectorizationSource.source_id)
        .order_by(VectorizationSource.source_id, distance)
        .subquery()
    )
    rows = await session.execute(
        select(best_per_source).order_by(best_per_source.c.distance).limit(limit)
    )
    return [
        SourceVectorMatch(
            source_id=row.source_id,
            chunk_id=row.chunk_id,
            score=min(max(1.0 - float(row.distance), 0.0), 1.0),
        )
        for row in rows
    ]
