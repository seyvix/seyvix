import asyncio
import hashlib
import hmac
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import Settings
from app.core.database import build_session_factory
from app.modules.vectorization.contracts import (
    VectorizationDocumentInput,
    VectorizationSubject,
    build_taxonomy_category_profile_vector_subject,
    vectorization_document_from_subject,
)
from app.modules.vectorization.infrastructure.chunking import ChunkingLimits, chunk_text
from app.modules.vectorization.infrastructure.embedding_providers import (
    FakeEmbeddingProvider,
    HttpEmbeddingProvider,
)
from app.modules.vectorization.models import (
    VectorizationChunk,
    VectorizationEmbedding,
    VectorizationJob,
    VectorizationSource,
)
from app.modules.vectorization.service import VectorizationService, compute_source_hash
from app.modules.vectorization.worker import VectorizationWorker

TELEGRAM_BOT_TOKEN = "123456:test-bot-token"


def _telegram_payload(telegram_id: int = 100500) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": telegram_id,
        "first_name": "User",
        "auth_date": int(datetime.now(UTC).timestamp()),
    }
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(payload.items()))
    secret_key = hashlib.sha256(TELEGRAM_BOT_TOKEN.encode("utf-8")).digest()
    payload["hash"] = hmac.new(
        secret_key,
        check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return payload


def _auth_headers(client: TestClient, telegram_id: int = 100500) -> dict[str, str]:
    response = client.post("/api/v1/auth/telegram-login", json=_telegram_payload(telegram_id))
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_category(
    client: TestClient,
    headers: dict[str, str],
    *,
    slug: str,
    name: str,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/taxonomy/categories",
        headers=headers,
        json={"slug": slug, "name": name, "description": f"{name} description"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _put_profile(
    client: TestClient, headers: dict[str, str], category_id: str, summary: str
) -> None:
    response = client.put(
        f"/api/v1/taxonomy/categories/{category_id}/profile",
        headers=headers,
        json={
            "summary": summary,
            "keywords": ["ai", "llm"],
            "positive_examples": ["LLM inference note"],
            "negative_examples": ["personal todo"],
        },
    )
    assert response.status_code == 200, response.text


def _worker_session_factory():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run DB-backed vectorization worker tests.")
    return build_session_factory(database_url)


def test_vectorization_subject_adapter_keeps_existing_contract() -> None:
    source_updated_at = datetime(2026, 4, 29, 10, 0, tzinfo=UTC)
    subject = build_taxonomy_category_profile_vector_subject(
        owner_user_id="user-id",
        category_id="category-id",
        category_path="ai/llm/inference",
        category_depth=2,
        source_text="Path: AI / LLM / Inference\nSummary: Models",
        source_updated_at=source_updated_at,
    )

    assert isinstance(subject, VectorizationSubject)
    assert subject.source_text.startswith("Path:")

    document = vectorization_document_from_subject(
        owner_user_id="user-id",
        source="taxonomy",
        source_type="category_profile",
        source_id="category-id",
        chunking_strategy="short_document",
        representation_type="category_profile",
        subject=subject,
    )

    assert document.external_id == "taxonomy_category_profile:category-id"
    assert document.text == subject.source_text
    assert document.metadata["category_path"] == "ai/llm/inference"
    assert document.dirty_key == source_updated_at.isoformat()


def test_vectorization_document_input_rejects_empty_text() -> None:
    with pytest.raises(ValidationError):
        VectorizationDocumentInput(
            owner_user_id="user-id",
            source="taxonomy",
            source_type="category_profile",
            source_id="category-id",
            external_id="taxonomy_category_profile:category-id",
            text=" ",
            metadata={"source": "taxonomy"},
            chunking_strategy="short_document",
            representation_type="category_profile",
            source_updated_at=datetime.now(UTC),
            dirty_key="dirty",
        )


def test_chunking_is_deterministic_and_enforces_limits() -> None:
    limits = ChunkingLimits(
        max_document_chars=1000,
        max_chunks_per_document=10,
        max_tokens_per_chunk=5,
        overlap_tokens=1,
        config_version="v1",
    )
    text = "one two three four five six seven eight nine"

    first = chunk_text(
        text,
        document_external_id="doc",
        strategy="default",
        metadata={"kind": "test"},
        limits=limits,
    )
    second = chunk_text(
        text,
        document_external_id="doc",
        strategy="default",
        metadata={"kind": "test"},
        limits=limits,
    )

    assert [chunk.text for chunk in first] == [chunk.text for chunk in second]
    assert [chunk.chunk_external_id for chunk in first] == ["doc:chunk:0", "doc:chunk:1"]
    with pytest.raises(ValueError, match="exceeds maximum"):
        chunk_text(
            "x" * 1001,
            document_external_id="doc",
            strategy="default",
            metadata={},
            limits=limits,
        )
    with pytest.raises(ValueError, match="empty"):
        chunk_text(
            " ",
            document_external_id="doc",
            strategy="short_document",
            metadata={},
            limits=limits,
        )


def test_source_hash_changes_with_text_and_indexing_config() -> None:
    document = VectorizationDocumentInput(
        owner_user_id="user-id",
        source="taxonomy",
        source_type="category_profile",
        source_id="category-id",
        external_id="taxonomy_category_profile:category-id",
        text="Text",
        metadata={"category_id": "category-id"},
        chunking_strategy="short_document",
        representation_type="category_profile",
        source_updated_at=datetime.now(UTC),
        dirty_key="dirty",
    )

    base = compute_source_hash(
        document,
        chunk_config_version="v1",
        provider="fake",
        model="fake-embedding",
        dimensions=384,
    )

    assert base != compute_source_hash(
        document.model_copy(update={"text": "Other text"}),
        chunk_config_version="v1",
        provider="fake",
        model="fake-embedding",
        dimensions=384,
    )
    assert base != compute_source_hash(
        document,
        chunk_config_version="v2",
        provider="fake",
        model="fake-embedding",
        dimensions=384,
    )
    assert base != compute_source_hash(
        document,
        chunk_config_version="v1",
        provider="http",
        model="fake-embedding",
        dimensions=384,
    )
    assert base != compute_source_hash(
        document,
        chunk_config_version="v1",
        provider="fake",
        model="other-model",
        dimensions=384,
    )
    assert base != compute_source_hash(
        document,
        chunk_config_version="v1",
        provider="fake",
        model="fake-embedding",
        dimensions=1024,
    )


@pytest.mark.asyncio
async def test_embedding_providers_are_deterministic_and_parse_http_shape() -> None:
    fake = FakeEmbeddingProvider()

    assert await fake.embed_texts(
        ["same"], model="fake-embedding", dimensions=4
    ) == await fake.embed_texts(["same"], model="fake-embedding", dimensions=4)
    assert len((await fake.embed_texts(["same"], model="fake-embedding", dimensions=4))[0]) == 4

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/embeddings"
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.3, 0.4]},
                    {"index": 0, "embedding": [0.1, 0.2]},
                ]
            },
        )

    provider = HttpEmbeddingProvider(
        base_url="http://embedding.local/v1",
        api_key="secret",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    assert await provider.embed_texts(["a", "b"], model="model", dimensions=2) == [
        [0.1, 0.2],
        [0.3, 0.4],
    ]


def test_authenticated_index_endpoint_enqueues_owner_scoped_job(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    category = _create_category(content_client, headers, slug="ai", name="AI")

    unauthorized = content_client.post(
        "/api/v1/vectorization/index",
        json={
            "source": "taxonomy",
            "source_type": "category_profile",
            "source_id": category["id"],
        },
    )
    assert unauthorized.status_code == 401

    response = content_client.post(
        "/api/v1/vectorization/index",
        headers=headers,
        json={
            "source": "taxonomy",
            "source_type": "category_profile",
            "source_id": category["id"],
            "priority": 50,
            "reason": "manual",
        },
    )
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "pending"

    jobs = content_client.get("/api/v1/vectorization/jobs", headers=headers)
    assert jobs.status_code == 200
    assert jobs.json()[0]["source_id"] == category["id"]
    assert jobs.json()[0]["priority"] == 50


def test_worker_processes_taxonomy_profile_and_reindex_is_idempotent(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    category = _create_category(content_client, headers, slug="ai", name="AI")
    _put_profile(content_client, headers, str(category["id"]), "Materials about AI systems.")

    enqueue = content_client.post(
        "/api/v1/vectorization/index",
        headers=headers,
        json={
            "source": "taxonomy",
            "source_type": "category_profile",
            "source_id": category["id"],
        },
    )
    assert enqueue.status_code == 202, enqueue.text

    async def scenario() -> tuple[int, int, int, str]:
        session_factory = _worker_session_factory()
        async with session_factory() as session:
            processed = await VectorizationWorker(session).run_once(limit=10)
            source = await session.scalar(select(VectorizationSource))
            assert source is not None
            initial_hash = source.source_hash
            chunks = list(await session.scalars(select(VectorizationChunk)))
            embeddings = list(await session.scalars(select(VectorizationEmbedding)))

            await VectorizationService(session).enqueue_index_request(
                owner_user_id=source.owner_user_id,
                source="taxonomy",
                source_type="category_profile",
                source_id=str(category["id"]),
                priority=100,
                reason="manual",
            )
            skipped = await VectorizationWorker(session).run_once(limit=10)
            await session.refresh(source)
            chunks_after = list(await session.scalars(select(VectorizationChunk)))
            embeddings_after = list(await session.scalars(select(VectorizationEmbedding)))

            assert skipped == 1
            assert source.source_hash == initial_hash
            assert len(chunks_after) == len(chunks)
            assert len(embeddings_after) == len(embeddings)
            return processed, len(chunks), len(embeddings), source.status

    processed, chunk_count, embedding_count, status = asyncio.run(scenario())

    assert processed == 1
    assert chunk_count >= 1
    assert embedding_count == chunk_count
    assert status == "synced"


def test_reindex_replaces_old_chunks_and_owner_isolation_is_enforced(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    other_headers = _auth_headers(content_client, telegram_id=200600)
    category = _create_category(content_client, headers, slug="ai", name="AI")
    _put_profile(content_client, headers, str(category["id"]), "Short profile.")

    response = content_client.post(
        "/api/v1/vectorization/index",
        headers=other_headers,
        json={
            "source": "taxonomy",
            "source_type": "category_profile",
            "source_id": category["id"],
        },
    )
    assert response.status_code == 202

    async def failed_owner_scenario() -> str:
        session_factory = _worker_session_factory()
        async with session_factory() as session:
            await VectorizationWorker(session).run_once(limit=10)
            job = await session.scalar(select(VectorizationJob))
            assert job is not None
            return str(job.last_error)

    assert "not found" in asyncio.run(failed_owner_scenario()).lower()

    enqueue = content_client.post(
        "/api/v1/vectorization/index",
        headers=headers,
        json={
            "source": "taxonomy",
            "source_type": "category_profile",
            "source_id": category["id"],
        },
    )
    assert enqueue.status_code == 202, enqueue.text

    async def first_index_scenario() -> tuple[set[str], str]:
        session_factory = _worker_session_factory()
        async with session_factory() as session:
            await VectorizationWorker(session).run_once(limit=10)
            old_chunk_ids = {
                chunk.id for chunk in await session.scalars(select(VectorizationChunk))
            }
            source = await session.scalar(select(VectorizationSource))
            assert source is not None
            return old_chunk_ids, source.owner_user_id

    old_chunk_ids, owner_user_id = asyncio.run(first_index_scenario())

    _put_profile(
        content_client,
        headers,
        str(category["id"]),
        " ".join(f"term-{index}" for index in range(40)),
    )

    async def reindex_scenario() -> tuple[int, int]:
        session_factory = _worker_session_factory()
        async with session_factory() as session:
            service = VectorizationService(session)
            source = await session.scalar(select(VectorizationSource))
            assert source is not None
            await service.enqueue_index_request(
                owner_user_id=owner_user_id,
                source="taxonomy",
                source_type="category_profile",
                source_id=str(category["id"]),
                priority=100,
                reason="manual",
            )
            await VectorizationWorker(session).run_once(limit=10)
            new_chunks = list(await session.scalars(select(VectorizationChunk)))
            assert old_chunk_ids.isdisjoint({chunk.id for chunk in new_chunks})
            return len(old_chunk_ids), len(new_chunks)

    old_count, new_count = asyncio.run(reindex_scenario())
    assert old_count >= 1
    assert new_count >= 1


def test_failed_provider_retries_until_failed() -> None:
    settings = Settings(vector_worker_lock_timeout_seconds=30)
    service = VectorizationService(session=None, settings=settings)  # type: ignore[arg-type]

    first_delay = service.retry_run_after(attempts=1)
    final_status = service.status_after_failure(attempts=3, max_attempts=3)

    assert first_delay > datetime.now(UTC)
    assert final_status == "failed"


def test_migration_creates_vector_extension_and_tables() -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20260429_0007_create_vectorization_tables.py"
    )
    content = migration_path.read_text(encoding="utf-8")

    assert "CREATE EXTENSION IF NOT EXISTS vector" in content
    assert '"vectorization_sources"' in content
    assert '"vectorization_documents"' in content
    assert '"vectorization_chunks"' in content
    assert '"vectorization_embeddings"' in content
    assert '"vectorization_jobs"' in content
