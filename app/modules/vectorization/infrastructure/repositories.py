from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.vectorization.infrastructure.chunking import TextChunk
from app.modules.vectorization.models import (
    VectorizationChunk,
    VectorizationDocument,
    VectorizationEmbedding,
    VectorizationJob,
    VectorizationSource,
)


class VectorizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def enqueue_job(
        self,
        *,
        owner_user_id: str,
        source: str,
        source_type: str,
        source_id: str,
        priority: int,
        reason: str | None,
    ) -> VectorizationJob:
        _ = reason
        job = VectorizationJob(
            owner_user_id=owner_user_id,
            job_type="index_source",
            source=source,
            source_type=source_type,
            source_id=source_id,
            status="pending",
            priority=priority,
        )
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def list_jobs(self, *, owner_user_id: str, limit: int) -> list[VectorizationJob]:
        query = (
            select(VectorizationJob)
            .where(VectorizationJob.owner_user_id == owner_user_id)
            .order_by(VectorizationJob.created_at.desc())
            .limit(limit)
        )
        return list(await self.session.scalars(query))

    async def list_sources(self, *, owner_user_id: str, limit: int) -> list[VectorizationSource]:
        query = (
            select(VectorizationSource)
            .where(VectorizationSource.owner_user_id == owner_user_id)
            .order_by(VectorizationSource.updated_at.desc())
            .limit(limit)
        )
        return list(await self.session.scalars(query))

    async def list_sources_by_scope(
        self,
        *,
        owner_user_id: str,
        source: str,
        source_type: str,
    ) -> list[VectorizationSource]:
        query = (
            select(VectorizationSource)
            .where(
                VectorizationSource.owner_user_id == owner_user_id,
                VectorizationSource.source == source,
                VectorizationSource.source_type == source_type,
                VectorizationSource.status != "deleted",
            )
            .order_by(VectorizationSource.updated_at.desc())
        )
        return list(await self.session.scalars(query))

    async def list_chunks(self, *, owner_user_id: str, limit: int) -> list[VectorizationChunk]:
        query = (
            select(VectorizationChunk)
            .where(VectorizationChunk.owner_user_id == owner_user_id)
            .order_by(VectorizationChunk.created_at.desc())
            .limit(limit)
        )
        return list(await self.session.scalars(query))

    async def claim_pending_jobs(
        self,
        *,
        limit: int,
        worker_id: str,
        lock_timeout_seconds: int,
    ) -> list[VectorizationJob]:
        now = datetime.now(UTC)
        stale_before = now - timedelta(seconds=lock_timeout_seconds)
        query = (
            select(VectorizationJob)
            .where(
                ((VectorizationJob.status == "pending") & (VectorizationJob.run_after <= now))
                | (
                    (VectorizationJob.status == "processing")
                    & (VectorizationJob.locked_at < stale_before)
                )
            )
            .order_by(VectorizationJob.priority.desc(), VectorizationJob.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        jobs = list(await self.session.scalars(query))
        for job in jobs:
            job.status = "processing"
            job.attempts += 1
            job.locked_at = now
            job.locked_by = worker_id
        await self.session.flush()
        return jobs

    async def get_source_by_external_id(
        self,
        *,
        owner_user_id: str,
        external_id: str,
    ) -> VectorizationSource | None:
        query = select(VectorizationSource).where(
            VectorizationSource.owner_user_id == owner_user_id,
            VectorizationSource.external_id == external_id,
        )
        return cast(VectorizationSource | None, await self.session.scalar(query))

    async def get_source_by_scope(
        self,
        *,
        owner_user_id: str,
        source: str,
        source_type: str,
        source_id: str,
    ) -> VectorizationSource | None:
        query = select(VectorizationSource).where(
            VectorizationSource.owner_user_id == owner_user_id,
            VectorizationSource.source == source,
            VectorizationSource.source_type == source_type,
            VectorizationSource.source_id == source_id,
        )
        return cast(VectorizationSource | None, await self.session.scalar(query))

    async def upsert_source(
        self,
        *,
        owner_user_id: str,
        source: str,
        source_type: str,
        source_id: str,
        external_id: str,
    ) -> VectorizationSource:
        source_record = await self.get_source_by_external_id(
            owner_user_id=owner_user_id,
            external_id=external_id,
        )
        if source_record is None:
            source_record = VectorizationSource(
                owner_user_id=owner_user_id,
                source=source,
                source_type=source_type,
                source_id=source_id,
                external_id=external_id,
                status="pending",
            )
            self.session.add(source_record)
            await self.session.flush()
        else:
            source_record.source = source
            source_record.source_type = source_type
            source_record.source_id = source_id
        return source_record

    async def replace_indexed_document(
        self,
        *,
        source_record: VectorizationSource,
        document_text: str,
        document_text_hash: str,
        document_metadata: dict[str, object],
        chunking_strategy: str,
        representation_type: str,
        chunks: Sequence[TextChunk],
        embeddings: Sequence[Sequence[float]],
        provider: str,
        model: str,
        dimensions: int,
        embedding_hashes: Sequence[str],
    ) -> None:
        existing_chunk_ids = list(
            await self.session.scalars(
                select(VectorizationChunk.id).where(
                    VectorizationChunk.source_record_id == source_record.id
                )
            )
        )
        if existing_chunk_ids:
            await self.session.execute(
                delete(VectorizationEmbedding).where(
                    VectorizationEmbedding.chunk_id.in_(existing_chunk_ids)
                )
            )
        await self.session.execute(
            delete(VectorizationChunk).where(
                VectorizationChunk.source_record_id == source_record.id
            )
        )
        await self.session.execute(
            delete(VectorizationDocument).where(
                VectorizationDocument.source_record_id == source_record.id
            )
        )
        document = VectorizationDocument(
            owner_user_id=source_record.owner_user_id,
            source_record_id=source_record.id,
            external_id=source_record.external_id,
            text=document_text,
            text_hash=document_text_hash,
            metadata_=document_metadata,
            chunking_strategy=chunking_strategy,
            representation_type=representation_type,
        )
        self.session.add(document)
        await self.session.flush()

        chunk_rows: list[VectorizationChunk] = []
        for chunk in chunks:
            chunk_row = VectorizationChunk(
                owner_user_id=source_record.owner_user_id,
                source_record_id=source_record.id,
                document_id=document.id,
                chunk_index=chunk.chunk_index,
                chunk_external_id=chunk.chunk_external_id,
                text=chunk.text,
                text_hash=chunk.text_hash,
                token_count=chunk.token_count,
                metadata_=chunk.metadata,
            )
            chunk_rows.append(chunk_row)
            self.session.add(chunk_row)
        await self.session.flush()

        for chunk_row, embedding, embedding_hash in zip(
            chunk_rows,
            embeddings,
            embedding_hashes,
            strict=True,
        ):
            self.session.add(
                VectorizationEmbedding(
                    owner_user_id=source_record.owner_user_id,
                    chunk_id=chunk_row.id,
                    provider=provider,
                    model=model,
                    dimensions=dimensions,
                    embedding=list(embedding),
                    embedding_hash=embedding_hash,
                )
            )

    async def delete_source_vectors(self, source_record: VectorizationSource) -> None:
        existing_chunk_ids = list(
            await self.session.scalars(
                select(VectorizationChunk.id).where(
                    VectorizationChunk.source_record_id == source_record.id
                )
            )
        )
        if existing_chunk_ids:
            await self.session.execute(
                delete(VectorizationEmbedding).where(
                    VectorizationEmbedding.chunk_id.in_(existing_chunk_ids)
                )
            )
        await self.session.execute(
            delete(VectorizationChunk).where(
                VectorizationChunk.source_record_id == source_record.id
            )
        )
        await self.session.execute(
            delete(VectorizationDocument).where(
                VectorizationDocument.source_record_id == source_record.id
            )
        )
        source_record.status = "deleted"
        source_record.source_hash = None
        source_record.last_error = None
