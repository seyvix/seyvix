import asyncio
import hashlib
import hmac
import json
import os
from datetime import UTC, datetime

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
    YandexEmbeddingProvider,
    build_embedding_provider,
)
from app.modules.vectorization.models import (
    VectorizationChunk,
    VectorizationDocument,
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
    settings_response = client.patch(
        "/api/v1/taxonomy/settings",
        headers=headers,
        json={"category_profile_editing_enabled": True},
    )
    assert settings_response.status_code == 200, settings_response.text
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


def test_chunking_strategies_are_explicit_and_stable() -> None:
    limits = ChunkingLimits(
        max_document_chars=1000,
        max_chunks_per_document=3,
        max_tokens_per_chunk=4,
        overlap_tokens=1,
        config_version="v1",
    )

    short = chunk_text(
        "profile summary keywords",
        document_external_id="taxonomy-doc",
        strategy="short_document",
        metadata={"source": "taxonomy"},
        limits=limits,
    )
    content = chunk_text(
        "one two three four five six seven eight nine ten",
        document_external_id="content-doc",
        strategy="content_text",
        metadata={"source": "content"},
        limits=limits,
    )
    snapshot = chunk_text(
        "one two three four five six",
        document_external_id="snapshot-doc",
        strategy="snapshot_text",
        metadata={},
        limits=limits,
    )
    metadata_only = chunk_text(
        "type title url tags taxonomy",
        document_external_id="metadata-doc",
        strategy="metadata_only",
        metadata={},
        limits=limits,
    )

    assert [chunk.text for chunk in short] == ["profile summary keywords"]
    assert [chunk.text for chunk in content] == [
        "one two three four",
        "four five six seven",
        "seven eight nine ten",
    ]
    assert [chunk.text for chunk in snapshot] == [
        "one two three four",
        "four five six",
    ]
    assert [chunk.text for chunk in metadata_only] == [
        "type title url tags",
        "tags taxonomy",
    ]
    assert [chunk.chunk_external_id for chunk in content] == [
        "content-doc:chunk:0",
        "content-doc:chunk:1",
        "content-doc:chunk:2",
    ]

    with pytest.raises(ValueError, match="maximum chunk count"):
        chunk_text(
            "one two three four five six seven eight nine ten eleven twelve thirteen fourteen",
            document_external_id="content-doc",
            strategy="content_text",
            metadata={},
            limits=limits,
        )
    with pytest.raises(ValueError, match="overlap"):
        chunk_text(
            "one two",
            document_external_id="content-doc",
            strategy="content_text",
            metadata={},
            limits=limits.__class__(
                max_document_chars=100,
                max_chunks_per_document=10,
                max_tokens_per_chunk=4,
                overlap_tokens=4,
                config_version="v1",
            ),
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


def test_ollama_provider_alias_uses_local_openai_compatible_default() -> None:
    provider = build_embedding_provider(
        provider_name="ollama",
        base_url=None,
        api_key=None,
        timeout_seconds=120,
    )

    assert isinstance(provider, HttpEmbeddingProvider)
    assert provider.base_url == "http://127.0.0.1:11434/v1"
    assert provider.api_key is None


@pytest.mark.asyncio
async def test_yandex_embedding_provider_uses_text_embedding_api_shape() -> None:
    requests: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "llm.api.cloud.yandex.net"
        assert request.url.path == "/foundationModels/v1/textEmbedding"
        assert request.headers["authorization"] == "Api-Key secret"
        body = json.loads(request.content)
        requests.append(body)
        assert body["modelUri"] == "emb://folder/text-search-doc/latest"
        assert "dim" not in body
        return httpx.Response(
            200,
            json={
                "embedding": ["0.1", "0.2"],
                "numTokens": "2",
                "modelVersion": "latest",
            },
        )

    provider = YandexEmbeddingProvider(
        base_url="https://llm.api.cloud.yandex.net/foundationModels/v1",
        api_key="secret",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    assert await provider.embed_texts(
        ["first", "second"],
        model="emb://folder/text-search-doc/latest",
        dimensions=2,
    ) == [[0.1, 0.2], [0.1, 0.2]]
    assert [request["text"] for request in requests] == ["first", "second"]


def test_yandex_provider_alias_uses_foundation_models_default() -> None:
    provider = build_embedding_provider(
        provider_name="yandex",
        base_url=None,
        api_key="secret",
        timeout_seconds=120,
    )

    assert isinstance(provider, YandexEmbeddingProvider)
    assert provider.base_url == "https://ai.api.cloud.yandex.net/foundationModels/v1"


@pytest.mark.asyncio
async def test_yandex_embedding_provider_normalizes_ai_studio_v1_base_url() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/foundationModels/v1/textEmbedding"
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(200, json={"embedding": ["0.1", "0.2"]})

    provider = YandexEmbeddingProvider(
        base_url="https://ai.api.cloud.yandex.net/v1",
        api_key="secret",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    assert provider.base_url == "https://ai.api.cloud.yandex.net/foundationModels/v1"
    assert await provider.embed_texts(
        ["text"],
        model="emb://folder/text-search-doc/latest",
        dimensions=2,
    ) == [[0.1, 0.2]]


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


def _create_text_note(
    client: TestClient,
    headers: dict[str, str],
    *,
    title: str,
    text: str,
    tag_names: list[str] | None = None,
    folder_path: str | None = None,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/notes",
        headers=headers,
        json={
            "media_type": "text",
            "title": title,
            "text": text,
            "tag_names": tag_names or [],
            "folder_path": folder_path,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_content_object_vectorization_provider_indexes_and_replaces_changed_content(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client, telegram_id=300500)
    other_headers = _auth_headers(content_client, telegram_id=300600)
    note = _create_text_note(
        content_client,
        headers,
        title="vLLM latency notes",
        text=" ".join(f"latency-token-{index}" for index in range(30)),
        tag_names=["AI", "Performance"],
        folder_path="research/ai",
    )

    denied = content_client.post(
        "/api/v1/vectorization/index",
        headers=other_headers,
        json={
            "source": "content",
            "source_type": "content_object",
            "source_id": note["id"],
        },
    )
    assert denied.status_code == 202

    async def failed_owner_scenario() -> str:
        session_factory = _worker_session_factory()
        async with session_factory() as session:
            await VectorizationWorker(session).run_once(limit=10)
            job = await session.scalar(
                select(VectorizationJob).where(VectorizationJob.last_error.is_not(None))
            )
            assert job is not None
            return str(job.last_error)

    assert "not found" in asyncio.run(failed_owner_scenario()).lower()

    enqueue = content_client.post(
        "/api/v1/vectorization/index",
        headers=headers,
        json={
            "source": "content",
            "source_type": "content_object",
            "source_id": note["id"],
        },
    )
    assert enqueue.status_code == 202, enqueue.text

    async def index_scenario() -> tuple[str, set[str], int, str, str]:
        session_factory = _worker_session_factory()
        async with session_factory() as session:
            processed = await VectorizationWorker(session).run_once(limit=10)
            assert processed == 1
            source = await session.scalar(
                select(VectorizationSource).where(VectorizationSource.source == "content")
            )
            assert source is not None
            document = await session.scalar(
                select(VectorizationDocument).where(
                    VectorizationDocument.source_record_id == source.id
                )
            )
            assert document is not None
            chunks = list(
                await session.scalars(
                    select(VectorizationChunk).where(
                        VectorizationChunk.source_record_id == source.id
                    )
                )
            )
            embeddings = list(
                await session.scalars(
                    select(VectorizationEmbedding)
                    .join(VectorizationChunk)
                    .where(VectorizationChunk.source_record_id == source.id)
                )
            )
            old_chunk_ids = {chunk.id for chunk in chunks}

            await VectorizationService(session).enqueue_index_request(
                owner_user_id=source.owner_user_id,
                source="content",
                source_type="content_object",
                source_id=str(note["id"]),
                priority=100,
                reason="manual",
            )
            skipped = await VectorizationWorker(session).run_once(limit=10)
            chunks_after = list(
                await session.scalars(
                    select(VectorizationChunk).where(
                        VectorizationChunk.source_record_id == source.id
                    )
                )
            )

            return (
                source.status,
                old_chunk_ids,
                skipped,
                document.text,
                f"{len(chunks_after)}:{len(embeddings)}",
            )

    status_value, old_chunk_ids, skipped, document_text, counts = asyncio.run(index_scenario())
    assert status_value == "synced"
    assert skipped == 1
    assert "Type: content_object" in document_text
    assert "Title: vLLM latency notes" in document_text
    assert "Tags: ai, performance" in document_text
    assert "Taxonomy category: research/ai" in document_text
    assert "Content:" in document_text
    assert counts.split(":")[0] == counts.split(":")[1]

    update = content_client.patch(
        f"/api/v1/notes/{note['slug']}",
        headers=headers,
        json={"title": "vLLM latency notes updated"},
    )
    assert update.status_code == 200, update.text

    async def changed_reindex_scenario() -> set[str]:
        session_factory = _worker_session_factory()
        async with session_factory() as session:
            source = await session.scalar(
                select(VectorizationSource).where(VectorizationSource.source == "content")
            )
            assert source is not None
            await VectorizationService(session).enqueue_index_request(
                owner_user_id=source.owner_user_id,
                source="content",
                source_type="content_object",
                source_id=str(note["id"]),
                priority=100,
                reason="manual",
            )
            await VectorizationWorker(session).run_once(limit=10)
            chunks = list(
                await session.scalars(
                    select(VectorizationChunk).where(
                        VectorizationChunk.source_record_id == source.id
                    )
                )
            )
            return {chunk.id for chunk in chunks}

    new_chunk_ids = asyncio.run(changed_reindex_scenario())
    assert old_chunk_ids.isdisjoint(new_chunk_ids)


def test_vectorization_reindex_and_delete_source_vectors_are_owner_scoped_and_idempotent(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client, telegram_id=300700)
    other_headers = _auth_headers(content_client, telegram_id=300800)
    category = _create_category(content_client, headers, slug="ai", name="AI")
    _put_profile(content_client, headers, str(category["id"]), "AI profile.")
    note = _create_text_note(
        content_client,
        headers,
        title="Indexed content",
        text="Content body for vector maintenance.",
    )

    for payload in [
        {
            "source": "taxonomy",
            "source_type": "category_profile",
            "source_id": category["id"],
        },
        {
            "source": "content",
            "source_type": "content_object",
            "source_id": note["id"],
        },
    ]:
        response = content_client.post("/api/v1/vectorization/index", headers=headers, json=payload)
        assert response.status_code == 202, response.text

    async def index_all() -> tuple[int, int]:
        session_factory = _worker_session_factory()
        async with session_factory() as session:
            processed = await VectorizationWorker(session).run_once(limit=10)
            source_count = len(list(await session.scalars(select(VectorizationSource))))
            chunk_count = len(list(await session.scalars(select(VectorizationChunk))))
            return source_count, chunk_count if processed == 2 else -1

    source_count, chunk_count = asyncio.run(index_all())
    assert source_count == 2
    assert chunk_count > 0

    other_reindex = content_client.post(
        "/api/v1/vectorization/reindex",
        headers=other_headers,
        json={"source": "taxonomy", "source_type": "category_profile"},
    )
    assert other_reindex.status_code == 202, other_reindex.text
    assert other_reindex.json()["job_count"] == 0

    reindex_taxonomy = content_client.post(
        "/api/v1/vectorization/reindex",
        headers=headers,
        json={"source": "taxonomy", "source_type": "category_profile"},
    )
    reindex_content = content_client.post(
        "/api/v1/vectorization/reindex",
        headers=headers,
        json={"source": "content", "source_type": "content_object"},
    )

    assert reindex_taxonomy.status_code == 202, reindex_taxonomy.text
    assert reindex_taxonomy.json()["job_count"] == 1
    assert reindex_content.status_code == 202, reindex_content.text
    assert reindex_content.json()["job_count"] == 1

    delete = content_client.post(
        "/api/v1/vectorization/delete-source-vectors",
        headers=headers,
        json={
            "source": "content",
            "source_type": "content_object",
            "source_id": note["id"],
        },
    )
    repeated_delete = content_client.post(
        "/api/v1/vectorization/delete-source-vectors",
        headers=headers,
        json={
            "source": "content",
            "source_type": "content_object",
            "source_id": note["id"],
        },
    )

    assert delete.status_code == 200, delete.text
    assert delete.json()["status"] == "deleted"
    assert repeated_delete.status_code == 200, repeated_delete.text
    assert repeated_delete.json()["status"] == "deleted"

    async def assert_deleted_source() -> tuple[str, int]:
        session_factory = _worker_session_factory()
        async with session_factory() as session:
            source = await session.scalar(
                select(VectorizationSource).where(
                    VectorizationSource.source == "content",
                    VectorizationSource.source_id == str(note["id"]),
                )
            )
            assert source is not None
            chunks = list(
                await session.scalars(
                    select(VectorizationChunk).where(
                        VectorizationChunk.source_record_id == source.id
                    )
                )
            )
            return source.status, len(chunks)

    deleted_status, deleted_chunks = asyncio.run(assert_deleted_source())
    assert deleted_status == "deleted"
    assert deleted_chunks == 0


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
            job = await session.scalar(
                select(VectorizationJob).where(VectorizationJob.last_error.is_not(None))
            )
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
