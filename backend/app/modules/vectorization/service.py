"""Request-side vectorization operations (REST). Indexing itself runs in the worker."""

from __future__ import annotations

from sqlalchemy import func, literal, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.vectorization.api import delete_source_vectors, enqueue_vectorization
from app.modules.vectorization.documents import is_supported_source
from app.modules.vectorization.models import (
    VectorizationChunk,
    VectorizationJob,
    VectorizationSource,
)
from app.modules.vectorization.schemas import VectorizationChunkResponse
from app.platform.jobs import JOB_PENDING, utcnow


class VectorizationProviderNotFoundError(Exception):
    pass


class VectorizationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def enqueue_index_request(
        self,
        *,
        owner_user_id: str,
        source: str,
        source_type: str,
        source_id: str,
        priority: int,
    ) -> VectorizationJob:
        _require_provider(source, source_type)
        await enqueue_vectorization(
            self.session,
            owner_user_id=owner_user_id,
            source=source,
            source_type=source_type,
            source_id=source_id,
            priority=priority,
        )
        job = await self.session.scalar(
            select(VectorizationJob).where(
                VectorizationJob.owner_user_id == owner_user_id,
                VectorizationJob.source == source,
                VectorizationJob.source_type == source_type,
                VectorizationJob.source_id == source_id,
            )
        )
        await self.session.commit()
        assert job is not None  # just upserted in this transaction
        return job

    async def enqueue_reindex_request(
        self,
        *,
        owner_user_id: str,
        source: str,
        source_type: str,
        priority: int,
    ) -> list[str]:
        """Re-queue every indexed item of a scope with one INSERT ... SELECT."""
        _require_provider(source, source_type)
        now = utcnow()
        selected = select(
            func.gen_random_uuid().cast(VectorizationJob.id.type),
            VectorizationSource.owner_user_id,
            VectorizationSource.source,
            VectorizationSource.source_type,
            VectorizationSource.source_id,
            literal(JOB_PENDING),
            literal(priority),
            literal(0),
            literal(now),
            literal(now),
            literal(now),
        ).where(
            VectorizationSource.owner_user_id == owner_user_id,
            VectorizationSource.source == source,
            VectorizationSource.source_type == source_type,
        )
        insert_statement = pg_insert(VectorizationJob).from_select(
            [
                "id",
                "owner_user_id",
                "source",
                "source_type",
                "source_id",
                "status",
                "priority",
                "attempts",
                "run_after",
                "created_at",
                "updated_at",
            ],
            selected,
        )
        statement = insert_statement.on_conflict_do_update(
            constraint="uq_vectorization_jobs_scope",
            set_={
                "status": JOB_PENDING,
                "attempts": 0,
                "run_after": now,
                "locked_at": None,
                "locked_by": None,
                "last_error": None,
                "priority": func.greatest(
                    VectorizationJob.priority, insert_statement.excluded.priority
                ),
                "updated_at": now,
            },
        ).returning(VectorizationJob.id)
        job_ids = list(await self.session.scalars(statement))
        await self.session.commit()
        return job_ids

    async def delete_source_vectors(
        self, *, owner_user_id: str, source: str, source_type: str, source_id: str
    ) -> str:
        await delete_source_vectors(
            self.session,
            owner_user_id=owner_user_id,
            source=source,
            source_type=source_type,
            source_id=source_id,
        )
        await self.session.commit()
        return "deleted"

    async def list_jobs(self, *, owner_user_id: str, limit: int) -> list[VectorizationJob]:
        return list(
            await self.session.scalars(
                select(VectorizationJob)
                .where(VectorizationJob.owner_user_id == owner_user_id)
                .order_by(VectorizationJob.updated_at.desc())
                .limit(limit)
            )
        )

    async def list_sources(self, *, owner_user_id: str, limit: int) -> list[VectorizationSource]:
        return list(
            await self.session.scalars(
                select(VectorizationSource)
                .where(VectorizationSource.owner_user_id == owner_user_id)
                .order_by(VectorizationSource.updated_at.desc())
                .limit(limit)
            )
        )

    async def list_chunks(
        self, *, owner_user_id: str, limit: int
    ) -> list[VectorizationChunkResponse]:
        rows = await self.session.execute(
            select(
                VectorizationChunk.id,
                VectorizationChunk.source_record_id,
                VectorizationChunk.chunk_index,
                VectorizationChunk.text_hash,
                VectorizationChunk.token_count,
                VectorizationChunk.embedding.is_not(None).label("has_embedding"),
                VectorizationChunk.created_at,
            )
            .where(VectorizationChunk.owner_user_id == owner_user_id)
            .order_by(VectorizationChunk.created_at.desc())
            .limit(limit)
        )
        return [
            VectorizationChunkResponse.model_validate(row, from_attributes=True) for row in rows
        ]


def _require_provider(source: str, source_type: str) -> None:
    if not is_supported_source(source, source_type):
        raise VectorizationProviderNotFoundError(
            f"No vectorization document provider for {source}/{source_type}."
        )
