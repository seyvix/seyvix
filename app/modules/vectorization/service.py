from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.modules.vectorization.contracts import VectorizationDocumentInput
from app.modules.vectorization.infrastructure.chunking import (
    ChunkingLimits,
    chunk_text,
    stable_json_hash,
)
from app.modules.vectorization.infrastructure.document_providers import (
    DocumentProviderRegistry,
    build_document_provider_registry,
)
from app.modules.vectorization.infrastructure.embedding_providers import (
    EmbeddingProvider,
    build_embedding_provider,
)
from app.modules.vectorization.infrastructure.repositories import VectorizationRepository
from app.modules.vectorization.models import VectorizationJob


class VectorizationProviderNotFoundError(Exception):
    pass


class VectorizationValidationError(Exception):
    pass


def compute_source_hash(
    document: VectorizationDocumentInput,
    *,
    chunk_config_version: str,
    provider: str,
    model: str,
    dimensions: int,
) -> str:
    payload = {
        "text": document.text,
        "metadata": document.metadata,
        "chunking_strategy": document.chunking_strategy,
        "representation_type": document.representation_type,
        "chunk_config_version": chunk_config_version,
        "provider": provider,
        "model": model,
        "dimensions": dimensions,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def compute_embedding_hash(vector: Sequence[float]) -> str:
    return hashlib.sha256(
        json.dumps(list(vector), separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


class VectorizationService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings | None = None,
        document_registry: DocumentProviderRegistry | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.repository = VectorizationRepository(session)
        self.document_registry = document_registry or build_document_provider_registry(session)
        self.embedding_provider = embedding_provider or build_embedding_provider(
            provider_name=self.settings.vector_embedding_provider,
            base_url=self.settings.vector_embedding_base_url,
            api_key=self.settings.vector_embedding_api_key,
            timeout_seconds=self.settings.vector_embedding_timeout_seconds,
        )

    async def enqueue_index_request(
        self,
        *,
        owner_user_id: str,
        source: str,
        source_type: str,
        source_id: str,
        priority: int,
        reason: str | None,
    ) -> VectorizationJob:
        if not self.document_registry.has_provider(source=source, source_type=source_type):
            raise VectorizationProviderNotFoundError(
                f"No vectorization document provider for {source}/{source_type}."
            )
        return await self.repository.enqueue_job(
            owner_user_id=owner_user_id,
            source=source,
            source_type=source_type,
            source_id=source_id,
            priority=priority,
            reason=reason,
        )

    async def process_job(self, job: VectorizationJob) -> None:
        provider = self.document_registry.get(source=job.source, source_type=job.source_type)
        document = await provider.build_document(
            owner_user_id=job.owner_user_id,
            source_id=job.source_id,
        )
        if document.source != job.source or document.source_type != job.source_type:
            raise VectorizationValidationError("Document provider returned mismatched source.")
        if len(document.text) > self.settings.vector_chunk_max_document_chars:
            raise VectorizationValidationError(
                f"Vectorization document exceeds maximum size of "
                f"{self.settings.vector_chunk_max_document_chars} chars."
            )

        job.external_id = document.external_id
        source_hash = compute_source_hash(
            document,
            chunk_config_version=self.settings.vector_chunk_config_version,
            provider=self.settings.vector_embedding_provider,
            model=self.settings.vector_embedding_model,
            dimensions=self.settings.vector_embedding_dimensions,
        )
        source_record = await self.repository.upsert_source(
            owner_user_id=document.owner_user_id,
            source=document.source,
            source_type=document.source_type,
            source_id=document.source_id,
            external_id=document.external_id,
        )
        if (
            source_record.status == "synced"
            and source_record.source_hash == source_hash
            and source_record.provider == self.settings.vector_embedding_provider
            and source_record.model == self.settings.vector_embedding_model
            and source_record.dimensions == self.settings.vector_embedding_dimensions
        ):
            self._succeed_job(job)
            return

        source_record.status = "processing"
        source_record.provider = self.settings.vector_embedding_provider
        source_record.model = self.settings.vector_embedding_model
        source_record.dimensions = self.settings.vector_embedding_dimensions
        source_record.last_error = None
        await self.session.flush()

        limits = self._chunking_limits()
        chunks = chunk_text(
            document.text,
            document_external_id=document.external_id,
            strategy=document.chunking_strategy,
            metadata=document.metadata,
            limits=limits,
        )
        embeddings: list[list[float]] = []
        batch_size = self.settings.vector_embedding_batch_size
        for index in range(0, len(chunks), batch_size):
            batch = chunks[index : index + batch_size]
            embeddings.extend(
                await self.embedding_provider.embed_texts(
                    [chunk.text for chunk in batch],
                    model=self.settings.vector_embedding_model,
                    dimensions=self.settings.vector_embedding_dimensions,
                )
            )
        for embedding in embeddings:
            if len(embedding) != self.settings.vector_embedding_dimensions:
                raise VectorizationValidationError(
                    "Embedding provider returned a vector with unexpected dimensions."
                )
        embedding_hashes = [compute_embedding_hash(embedding) for embedding in embeddings]
        await self.repository.replace_indexed_document(
            source_record=source_record,
            document_text=document.text,
            document_text_hash=stable_json_hash(document.text),
            document_metadata=document.metadata,
            chunking_strategy=document.chunking_strategy,
            representation_type=document.representation_type,
            chunks=chunks,
            embeddings=embeddings,
            provider=self.settings.vector_embedding_provider,
            model=self.settings.vector_embedding_model,
            dimensions=self.settings.vector_embedding_dimensions,
            embedding_hashes=embedding_hashes,
        )
        source_record.source_hash = source_hash
        source_record.status = "synced"
        source_record.last_indexed_at = datetime.now(UTC)
        source_record.last_error = None
        self._succeed_job(job)

    def retry_run_after(self, *, attempts: int) -> datetime:
        delay_seconds = min(300, 2 ** max(attempts - 1, 0) * 10)
        return datetime.now(UTC) + timedelta(seconds=delay_seconds)

    @staticmethod
    def status_after_failure(*, attempts: int, max_attempts: int) -> str:
        return "pending" if attempts < max_attempts else "failed"

    async def mark_failed(self, job: VectorizationJob, message: str) -> None:
        job.status = self.status_after_failure(attempts=job.attempts, max_attempts=job.max_attempts)
        job.last_error = message[:4000]
        job.locked_at = None
        job.locked_by = None
        if job.status == "pending":
            job.run_after = self.retry_run_after(attempts=job.attempts)
        if job.external_id is not None:
            source_record = await self.repository.get_source_by_external_id(
                owner_user_id=job.owner_user_id,
                external_id=job.external_id,
            )
            if source_record is not None:
                source_record.status = "failed" if job.status == "failed" else "stale"
                source_record.last_error = message[:4000]

    def _chunking_limits(self) -> ChunkingLimits:
        return ChunkingLimits(
            max_document_chars=self.settings.vector_chunk_max_document_chars,
            max_chunks_per_document=self.settings.vector_chunk_max_chunks_per_document,
            max_tokens_per_chunk=self.settings.vector_chunk_default_max_tokens,
            overlap_tokens=self.settings.vector_chunk_default_overlap_tokens,
            config_version=self.settings.vector_chunk_config_version,
        )

    @staticmethod
    def _succeed_job(job: VectorizationJob) -> None:
        job.status = "succeeded"
        job.locked_at = None
        job.locked_by = None
        job.last_error = None
