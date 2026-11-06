"""Vectorization worker: keeps the search index (chunks + FTS + embeddings) in sync.

Two independent duties inside one job runner:

1. Index jobs (`vectorization_jobs`): rebuild an item's chunks when its text changed. No AI
   calls here, so the FTS index stays fresh even when AI is disabled or down. Unchanged text
   (same content hash) is a no-op; chunks whose text is unchanged keep their embeddings.
2. Embedding loop: embeds chunks with a NULL embedding in batches across items (one request
   per `ai_embedding_batch_size` chunks). This is also the backfill path when AI gets enabled
   later or the embedding model changes. AI failures pause the loop with exponential backoff
   (circuit breaker) instead of failing jobs or retrying in a tight loop.

Run a single vectorization worker process; two would only waste embedding calls (results stay
correct: writes are guarded by `embedding IS NULL AND text_hash = ...`).
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, cast
from uuid import uuid4

from pgvector.sqlalchemy import HALFVEC  # type: ignore[import-untyped]
from sqlalchemy import Table, bindparam, delete, exists, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.events import EventEnvelope
from app.core.logging import get_logger
from app.modules.llm.client import AIError, get_ai_client
from app.modules.vectorization.api import delete_source_vectors, enqueue_vectorization
from app.modules.vectorization.chunking import ChunkingConfig, TextChunk, chunk_text, content_hash
from app.modules.vectorization.documents import (
    SOURCE_CONTENT,
    UnsupportedSourceError,
    build_document_text,
)
from app.modules.vectorization.models import (
    EMBEDDING_DIMENSIONS,
    VectorizationChunk,
    VectorizationJob,
    VectorizationSource,
)
from app.platform.jobs import JOB_PROCESSING, JobQueue, utcnow
from app.worker.context import WorkerContext

logger = get_logger(__name__)

EMBED_PAUSE_BASE_SECONDS = 30.0
EMBED_PAUSE_MAX_SECONDS = 900.0
MODEL_CHECK_INTERVAL_SECONDS = 600.0
MODEL_RESET_BATCH = 500

_chunks = cast(Table, VectorizationChunk.__table__)


class VectorizationEventHandler:
    """content.object.deleted → drop vectors; snapshot text completed → (re)index."""

    def __init__(self, session: AsyncSession, ctx: WorkerContext) -> None:
        self.session = session
        self.ctx = ctx

    async def handle_event(self, envelope: EventEnvelope) -> None:
        owner_user_id = envelope.user_id
        content_object_id = str(envelope.payload.get("content_object_id") or envelope.entity_id)
        if not owner_user_id:
            logger.warning(
                "vectorization.event.missing_user",
                event_id=envelope.event_id,
                event_name=envelope.event_name,
            )
            return
        source, source_type = SOURCE_CONTENT
        if envelope.event_name == "content.object.deleted":
            await delete_source_vectors(
                self.session,
                owner_user_id=owner_user_id,
                source=source,
                source_type=source_type,
                source_id=content_object_id,
            )
        elif envelope.event_name == "snapshot.text_representation.completed":
            await enqueue_vectorization(
                self.session,
                owner_user_id=owner_user_id,
                source=source,
                source_type=source_type,
                source_id=content_object_id,
            )


@dataclass(frozen=True, slots=True)
class _ClaimedJob:
    id: str
    owner_user_id: str
    source: str
    source_type: str
    source_id: str


class VectorizationJobRunner:
    def __init__(self, ctx: WorkerContext) -> None:
        self.ctx = ctx
        self.settings = ctx.settings
        self.queue = JobQueue(
            VectorizationJob,
            lease_seconds=ctx.settings.worker_job_lease_seconds,
            worker_id=ctx.worker_id,
        )
        self.chunking = ChunkingConfig.from_settings(ctx.settings)
        self._embed_failures = 0
        self._embed_paused_until = 0.0
        self._next_model_check = 0.0

    async def run_once(self) -> int:
        processed = await self._process_jobs()
        embedded = await self._embed_pending()
        return processed + embedded

    async def aclose(self) -> None:
        return None  # the AI client is process-wide and closed by the worker on shutdown

    # --- index jobs ----------------------------------------------------------------------
    async def _process_jobs(self) -> int:
        async with self.ctx.session_factory() as session:
            jobs = await self.queue.claim(session, limit=self.settings.vector_job_batch_size)
            claimed = [
                _ClaimedJob(
                    id=job.id,
                    owner_user_id=job.owner_user_id,
                    source=job.source,
                    source_type=job.source_type,
                    source_id=job.source_id,
                )
                for job in jobs
            ]
            await session.commit()
        for job in claimed:
            try:
                await self._index(job)
            except Exception as exc:  # noqa: BLE001 - isolate one bad item from the batch
                permanent = isinstance(exc, UnsupportedSourceError)
                logger.error(
                    "vectorization.job.failed",
                    job_id=job.id,
                    source=job.source,
                    source_type=job.source_type,
                    source_id=job.source_id,
                    permanent=permanent,
                    error=str(exc),
                    exc_info=True,
                )
                await self._fail(job, f"{type(exc).__name__}: {exc}", retryable=not permanent)
        return len(claimed)

    async def _index(self, job: _ClaimedJob) -> None:
        async with self.ctx.session_factory() as session:
            text = await build_document_text(
                session,
                self.ctx.storage,
                owner_user_id=job.owner_user_id,
                source=job.source,
                source_type=job.source_type,
                source_id=job.source_id,
                max_chars=self.chunking.max_document_chars,
            )
            scope = _scope(job)
            if text is None:  # the item is gone: drop it from the index
                if await self._lock_own_job(session, job) is None:
                    return
                await session.execute(delete(VectorizationSource).where(*scope))
                await self._succeed(session, job, outcome="removed")
                return
            new_hash = content_hash(text, self.chunking)
            source_row = await session.scalar(select(VectorizationSource).where(*scope))
            if source_row is not None and source_row.content_hash == new_hash:
                if await self._lock_own_job(session, job) is not None:
                    await self._succeed(session, job, outcome="unchanged")
                return
            chunks = chunk_text(text, self.chunking)
            if await self._lock_own_job(session, job) is None:
                return
            await self._write_chunks(session, job, source_row, new_hash, chunks)
            await self._succeed(session, job, outcome="indexed", chunks=len(chunks))

    async def _write_chunks(
        self,
        session: AsyncSession,
        job: _ClaimedJob,
        source_row: VectorizationSource | None,
        new_hash: str,
        chunks: list[TextChunk],
    ) -> None:
        model = self.settings.ai_embedding_model
        # text_hash -> [(chunk id, reusable embedding)]
        pool: dict[str, list[tuple[str, bool]]] = defaultdict(list)
        if source_row is None:
            source_row = VectorizationSource(
                id=str(uuid4()),
                owner_user_id=job.owner_user_id,
                source=job.source,
                source_type=job.source_type,
                source_id=job.source_id,
                content_hash=new_hash,
            )
            session.add(source_row)
            await session.flush()
        else:
            existing = (
                await session.execute(
                    select(
                        VectorizationChunk.id,
                        VectorizationChunk.text_hash,
                        VectorizationChunk.embedding.is_not(None),
                    ).where(VectorizationChunk.source_record_id == source_row.id)
                )
            ).all()
            same_model = source_row.embedding_model == model
            if existing:
                # Free the (source, chunk_index) slots so kept rows can be renumbered.
                await session.execute(
                    update(VectorizationChunk)
                    .where(VectorizationChunk.source_record_id == source_row.id)
                    .values(
                        chunk_index=-1 - VectorizationChunk.chunk_index,
                        **({} if same_model else {"embedding": None}),
                    )
                )
            for chunk_id, hash_value, has_embedding in existing:
                pool[hash_value].append((chunk_id, bool(has_embedding) and same_model))

        renumber: list[dict[str, Any]] = []
        new_rows: list[dict[str, Any]] = []
        missing_embeddings = False
        now = utcnow()
        for chunk in chunks:
            bucket = pool.get(chunk.text_hash)
            if bucket:
                chunk_id, has_embedding = bucket.pop()
                renumber.append({"chunk_id": chunk_id, "new_index": chunk.index})
                missing_embeddings = missing_embeddings or not has_embedding
                continue
            missing_embeddings = True
            new_rows.append(
                {
                    "id": str(uuid4()),
                    "source_record_id": source_row.id,
                    "owner_user_id": job.owner_user_id,
                    "chunk_index": chunk.index,
                    "text": chunk.text,
                    "text_hash": chunk.text_hash,
                    "token_count": chunk.token_count,
                    "created_at": now,
                }
            )
        stale_ids = [chunk_id for bucket in pool.values() for chunk_id, _ in bucket]
        if stale_ids:
            await session.execute(
                delete(VectorizationChunk).where(VectorizationChunk.id.in_(stale_ids))
            )
        if renumber:
            await session.execute(
                _chunks.update()
                .where(_chunks.c.id == bindparam("chunk_id"))
                .values(chunk_index=bindparam("new_index")),
                renumber,
            )
        if new_rows:
            await session.execute(insert(_chunks), new_rows)
        source_row.content_hash = new_hash
        source_row.chunk_count = len(chunks)
        source_row.needs_embedding = missing_embeddings
        source_row.embedding_model = model
        source_row.indexed_at = now
        source_row.last_error = None

    async def _lock_own_job(
        self, session: AsyncSession, job: _ClaimedJob
    ) -> VectorizationJob | None:
        """Row-lock the job and confirm we still own it (not reset, cancelled or re-leased)."""
        row = await session.get(
            VectorizationJob, job.id, with_for_update=True, populate_existing=True
        )
        if row is None or row.status != JOB_PROCESSING or row.locked_by != self.ctx.worker_id:
            logger.info("vectorization.job.superseded", job_id=job.id, source_id=job.source_id)
            await session.rollback()
            return None
        return row

    async def _succeed(
        self, session: AsyncSession, job: _ClaimedJob, *, outcome: str, chunks: int = 0
    ) -> None:
        row = await session.get(VectorizationJob, job.id)
        if row is not None:
            JobQueue.succeed(row)
        await session.commit()
        logger.info(
            "vectorization.job.done",
            job_id=job.id,
            source=job.source,
            source_id=job.source_id,
            outcome=outcome,
            chunks=chunks,
        )

    async def _fail(self, job: _ClaimedJob, error: str, *, retryable: bool) -> None:
        async with self.ctx.session_factory() as session:
            row = await self._lock_own_job(session, job)
            if row is None:
                return
            JobQueue.fail(row, error, retryable=retryable)
            await session.commit()

    # --- embedding loop ------------------------------------------------------------------
    async def _embed_pending(self) -> int:
        client = get_ai_client(self.settings)
        if client is None or time.monotonic() < self._embed_paused_until:
            return 0
        if time.monotonic() >= self._next_model_check:
            await self._reset_stale_model_embeddings()
            self._next_model_check = time.monotonic() + MODEL_CHECK_INTERVAL_SECONDS

        async with self.ctx.session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        VectorizationChunk.id,
                        VectorizationChunk.text,
                        VectorizationChunk.text_hash,
                        VectorizationChunk.source_record_id,
                    )
                    .join(
                        VectorizationSource,
                        VectorizationSource.id == VectorizationChunk.source_record_id,
                    )
                    .where(
                        VectorizationSource.needs_embedding.is_(True),
                        VectorizationChunk.embedding.is_(None),
                    )
                    .order_by(VectorizationSource.updated_at.desc(), VectorizationChunk.chunk_index)
                    .limit(self.settings.ai_embedding_batch_size)
                )
            ).all()
            if not rows:
                # Clear flags left set on items whose chunks are all embedded (or deleted).
                await session.execute(
                    update(VectorizationSource)
                    .where(VectorizationSource.needs_embedding.is_(True), ~_has_missing())
                    .values(needs_embedding=False)
                )
            await session.commit()
        if not rows:
            return 0

        source_ids = {row.source_record_id for row in rows}
        try:
            vectors = await client.embed([row.text for row in rows])
        except AIError as exc:
            self._embed_failures += 1
            pause = min(
                EMBED_PAUSE_BASE_SECONDS * 2 ** (self._embed_failures - 1), EMBED_PAUSE_MAX_SECONDS
            )
            self._embed_paused_until = time.monotonic() + pause
            logger.warning(
                "vectorization.embedding.paused",
                error=str(exc),
                failures=self._embed_failures,
                retry_in_seconds=pause,
            )
            async with self.ctx.session_factory() as session:
                await session.execute(
                    update(VectorizationSource)
                    .where(VectorizationSource.id.in_(source_ids))
                    .values(last_error=f"embedding: {exc}"[:2000])
                )
                await session.commit()
            return 0
        self._embed_failures = 0

        async with self.ctx.session_factory() as session:
            await session.execute(
                _chunks.update()
                .where(
                    _chunks.c.id == bindparam("chunk_id"),
                    _chunks.c.text_hash == bindparam("chunk_hash"),
                    _chunks.c.embedding.is_(None),
                )
                .values(embedding=bindparam("vector", type_=HALFVEC(EMBEDDING_DIMENSIONS))),
                [
                    {"chunk_id": row.id, "chunk_hash": row.text_hash, "vector": vector}
                    for row, vector in zip(rows, vectors, strict=True)
                ],
            )
            await session.execute(
                update(VectorizationSource)
                .where(VectorizationSource.id.in_(source_ids))
                .values(needs_embedding=_has_missing(), last_error=None)
            )
            await session.commit()
        logger.info("vectorization.embedding.batch", chunks=len(rows), sources=len(source_ids))
        return len(rows)

    async def _reset_stale_model_embeddings(self) -> None:
        """After AI_EMBEDDING_MODEL changes, drop old vectors so the loop re-embeds them."""
        model = self.settings.ai_embedding_model
        while True:
            async with self.ctx.session_factory() as session:
                ids = list(
                    await session.scalars(
                        select(VectorizationSource.id)
                        .where(
                            VectorizationSource.embedding_model.is_not(None),
                            VectorizationSource.embedding_model != model,
                        )
                        .limit(MODEL_RESET_BATCH)
                    )
                )
                if not ids:
                    return
                await session.execute(
                    update(VectorizationChunk)
                    .where(VectorizationChunk.source_record_id.in_(ids))
                    .values(embedding=None)
                )
                await session.execute(
                    update(VectorizationSource)
                    .where(VectorizationSource.id.in_(ids))
                    .values(
                        embedding_model=model,
                        needs_embedding=VectorizationSource.chunk_count > 0,
                    )
                )
                await session.commit()
            logger.info("vectorization.embedding.model_reset", sources=len(ids), model=model)
            if len(ids) < MODEL_RESET_BATCH:
                return


def _scope(job: _ClaimedJob) -> tuple[Any, ...]:
    return (
        VectorizationSource.owner_user_id == job.owner_user_id,
        VectorizationSource.source == job.source,
        VectorizationSource.source_type == job.source_type,
        VectorizationSource.source_id == job.source_id,
    )


def _has_missing() -> Any:
    return (
        exists()
        .where(
            VectorizationChunk.source_record_id == VectorizationSource.id,
            VectorizationChunk.embedding.is_(None),
        )
        .correlate(VectorizationSource)
    )
