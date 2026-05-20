import asyncio
import hashlib
import hmac
import os
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import build_session_factory
from app.modules.content.service import ContentService
from app.modules.search.service import SemanticSearchService
from app.modules.vectorization.contracts import (
    VectorizedChunkFullTextSearchResult,
    VectorizedChunkSearchResult,
)
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
    response = client.post(
        "/api/v1/auth/telegram-login", json=_telegram_payload(telegram_id)
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _auth_session(
    client: TestClient, telegram_id: int = 100500
) -> tuple[dict[str, str], str]:
    response = client.post(
        "/api/v1/auth/telegram-login", json=_telegram_payload(telegram_id)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, str(body["user"]["id"])


def _worker_session_factory():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run DB-backed semantic search tests.")
    return build_session_factory(database_url)


def _create_indexed_category_profile(
    client: TestClient,
    headers: dict[str, str],
    *,
    slug: str,
    summary: str,
) -> dict[str, object]:
    category_response = client.post(
        "/api/v1/taxonomy/categories",
        headers=headers,
        json={
            "slug": slug,
            "name": slug.replace("-", " ").title(),
            "description": f"{slug} description",
        },
    )
    assert category_response.status_code == 201, category_response.text
    category = category_response.json()
    profile_response = client.put(
        f"/api/v1/taxonomy/categories/{category['id']}/profile",
        headers=headers,
        json={
            "summary": summary,
            "keywords": ["semantic", "search"],
            "positive_examples": ["semantic chunk search"],
            "negative_examples": ["unrelated owner data"],
        },
    )
    assert profile_response.status_code == 200, profile_response.text
    enqueue_response = client.post(
        "/api/v1/vectorization/index",
        headers=headers,
        json={
            "source": "taxonomy",
            "source_type": "category_profile",
            "source_id": category["id"],
        },
    )
    assert enqueue_response.status_code == 202, enqueue_response.text

    async def run_worker() -> int:
        session_factory = _worker_session_factory()
        async with session_factory() as session:
            return await VectorizationWorker(session).run_once(limit=10)

    assert asyncio.run(run_worker()) == 1
    return category


def _create_indexed_content_object(
    client: TestClient,
    headers: dict[str, str],
    *,
    title: str,
    text: str,
) -> dict[str, object]:
    note_response = client.post(
        "/api/v1/notes",
        headers=headers,
        json={
            "media_type": "text",
            "title": title,
            "text": text,
            "tag_names": ["semantic"],
        },
    )
    assert note_response.status_code == 201, note_response.text
    note = note_response.json()
    enqueue_response = client.post(
        "/api/v1/vectorization/index",
        headers=headers,
        json={
            "source": "content",
            "source_type": "content_object",
            "source_id": note["id"],
        },
    )
    assert enqueue_response.status_code == 202, enqueue_response.text

    async def run_worker() -> int:
        session_factory = _worker_session_factory()
        async with session_factory() as session:
            return await VectorizationWorker(session).run_once(limit=10)

    assert asyncio.run(run_worker()) == 1
    return note


def _create_indexed_content_object_with_source(
    client: TestClient,
    headers: dict[str, str],
    *,
    owner_user_id: str,
    media_type: str,
    title: str,
    text: str,
    source_provider: str,
) -> dict[str, object]:
    note_response = client.post(
        "/api/v1/notes",
        headers=headers,
        json={
            "media_type": media_type,
            "title": title,
            "text": text,
            "tag_names": ["hybrid"],
        },
    )
    assert note_response.status_code == 201, note_response.text
    note = note_response.json()

    async def attach_source() -> None:
        session_factory = _worker_session_factory()
        async with session_factory() as session:
            await ContentService(session).attach_source_metadata(
                owner_user_id=owner_user_id,
                content_object_id=str(note["id"]),
                source={
                    "provider": source_provider,
                    "provider_label": source_provider.title(),
                    "external_id": f"{source_provider}:{note['id']}",
                    "original_created_at": datetime(2026, 5, 17, 12, 0, tzinfo=UTC),
                },
            )
            await session.commit()

    asyncio.run(attach_source())

    enqueue_response = client.post(
        "/api/v1/vectorization/index",
        headers=headers,
        json={
            "source": "content",
            "source_type": "content_object",
            "source_id": note["id"],
        },
    )
    assert enqueue_response.status_code == 202, enqueue_response.text

    async def run_worker() -> int:
        session_factory = _worker_session_factory()
        async with session_factory() as session:
            return await VectorizationWorker(session).run_once(limit=10)

    assert asyncio.run(run_worker()) == 1
    return note


def _chunk_result(chunk_id: str, *, text: str = "Search result text") -> dict[str, Any]:
    return {
        "source": "content",
        "source_type": "content_object",
        "source_id": chunk_id,
        "external_id": f"content_object:{chunk_id}",
        "chunk_id": chunk_id,
        "chunk_external_id": f"content_object:{chunk_id}:chunk:0",
        "text": text,
        "metadata": {"media_type": "text"},
    }


class _FakeEmbeddingProvider:
    def __init__(self) -> None:
        self.text_batches: list[list[str]] = []

    async def embed_texts(
        self,
        texts: list[str],
        *,
        model: str,
        dimensions: int,
    ) -> list[list[float]]:
        self.text_batches.append(texts)
        return [[float(index + 1)] * dimensions for index, _ in enumerate(texts)]


class _FakeHybridChunkReader:
    def __init__(self) -> None:
        self.full_text_queries: list[str] = []
        self.vector_limits: list[int] = []
        self.full_text_limits: list[int] = []

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
        filters: object | None = None,
    ) -> list[VectorizedChunkSearchResult]:
        self.vector_limits.append(limit)
        return [
            VectorizedChunkSearchResult(
                **_chunk_result("shared"),
                distance=0.1,
                score=0.9,
            ),
            VectorizedChunkSearchResult(
                **_chunk_result("vector-only"),
                distance=0.2,
                score=0.8,
            ),
        ]

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
        filters: object | None = None,
    ) -> list[VectorizedChunkFullTextSearchResult]:
        self.full_text_queries.append(query)
        self.full_text_limits.append(limit)
        return [
            VectorizedChunkFullTextSearchResult(
                **_chunk_result("shared"),
                full_text_score=0.75,
            ),
            VectorizedChunkFullTextSearchResult(
                **_chunk_result("fts-only"),
                full_text_score=0.5,
            ),
        ]


class _FakeQueryExpansionLLM:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def generate_structured(
        self,
        *,
        prompt: str,
        schema: dict[str, Any],
        model_config: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append(
            {"prompt": prompt, "schema": schema, "model_config": model_config}
        )
        return {"queries": ["semantic retrieval", "postgres fts", "vector search"]}


@pytest.mark.asyncio
async def test_hybrid_search_expands_query_and_merges_vector_and_fts_with_rrf() -> None:
    embeddings = _FakeEmbeddingProvider()
    chunk_reader = _FakeHybridChunkReader()
    llm = _FakeQueryExpansionLLM()
    service = SemanticSearchService(
        cast(AsyncSession, object()),
        settings=Settings(
            search_query_expansion_enabled=True,
            search_query_expansion_max_queries=3,
            search_hybrid_candidate_multiplier=2,
        ),
        embedding_provider=embeddings,
        chunk_reader=chunk_reader,
        llm_generator=llm,
    )

    response = await service.hybrid_search(
        owner_user_id="user-id",
        query="vector search",
        limit=2,
    )

    assert response.query == "vector search"
    assert response.expanded_queries == [
        "vector search",
        "semantic retrieval",
        "postgres fts",
    ]
    assert embeddings.text_batches == [
        ["vector search", "semantic retrieval", "postgres fts"]
    ]
    assert chunk_reader.full_text_queries == [
        "vector search",
        "semantic retrieval",
        "postgres fts",
    ]
    assert chunk_reader.vector_limits == [4, 4, 4]
    assert chunk_reader.full_text_limits == [4, 4, 4]
    assert [result.chunk_id for result in response.results] == ["shared", "vector-only"]
    assert response.results[0].vector_rank == 1
    assert response.results[0].full_text_rank == 1
    assert response.results[0].score > response.results[1].score


def test_semantic_search_requires_authentication(content_client: TestClient) -> None:
    response = content_client.post(
        "/api/v1/search/semantic",
        json={"query": "taxonomy profile", "limit": 5},
    )

    assert response.status_code == 401


def test_semantic_search_returns_owner_scoped_vectorized_chunks(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client, telegram_id=300100)
    other_headers = _auth_headers(content_client, telegram_id=300200)
    category = _create_indexed_category_profile(
        content_client,
        headers,
        slug="semantic-search",
        summary="Materials about semantic search over vectorized chunks.",
    )

    response = content_client.post(
        "/api/v1/search/semantic",
        headers=headers,
        json={"query": "semantic search chunks", "limit": 5},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["query"] == "semantic search chunks"
    assert body["results"]
    assert body["results"][0]["source"] == "taxonomy"
    assert body["results"][0]["source_type"] == "category_profile"
    assert body["results"][0]["source_id"] == category["id"]
    assert (
        body["results"][0]["external_id"]
        == f"taxonomy_category_profile:{category['id']}"
    )
    assert "Semantic Search" in body["results"][0]["text"]
    assert body["results"][0]["score"] <= 1

    other_response = content_client.post(
        "/api/v1/search/semantic",
        headers=other_headers,
        json={"query": "semantic search chunks", "limit": 5},
    )

    assert other_response.status_code == 200, other_response.text
    assert other_response.json()["results"] == []


def test_semantic_search_source_filters_scope_results(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client, telegram_id=300300)
    taxonomy_category = _create_indexed_category_profile(
        content_client,
        headers,
        slug="taxonomy-only",
        summary="Taxonomy profile for search filtering.",
    )
    content_note = _create_indexed_content_object(
        content_client,
        headers,
        title="Content search note",
        text="Content object body for filtered semantic search.",
    )

    unfiltered = content_client.post(
        "/api/v1/search/semantic",
        headers=headers,
        json={"query": "semantic search", "limit": 10},
    )
    taxonomy_only = content_client.post(
        "/api/v1/search/semantic",
        headers=headers,
        json={
            "query": "semantic search",
            "source": "taxonomy",
            "source_type": "category_profile",
            "limit": 10,
        },
    )
    content_only = content_client.post(
        "/api/v1/search/semantic",
        headers=headers,
        json={
            "query": "semantic search",
            "source": "content",
            "source_type": "content_object",
            "limit": 10,
        },
    )
    one_source = content_client.post(
        "/api/v1/search/semantic",
        headers=headers,
        json={
            "query": "semantic search",
            "source": "content",
            "source_type": "content_object",
            "source_id": content_note["id"],
            "limit": 10,
        },
    )

    assert unfiltered.status_code == 200, unfiltered.text
    assert {result["source"] for result in unfiltered.json()["results"]} == {
        "taxonomy",
        "content",
    }
    assert taxonomy_only.status_code == 200, taxonomy_only.text
    assert {result["source"] for result in taxonomy_only.json()["results"]} == {
        "taxonomy"
    }
    assert taxonomy_only.json()["results"][0]["source_id"] == taxonomy_category["id"]
    assert content_only.status_code == 200, content_only.text
    assert {result["source"] for result in content_only.json()["results"]} == {
        "content"
    }
    assert one_source.status_code == 200, one_source.text
    assert {result["source_id"] for result in one_source.json()["results"]} == {
        content_note["id"]
    }


def test_hybrid_search_filters_by_metadata_before_ranking(
    content_client: TestClient,
) -> None:
    headers, owner_user_id = _auth_session(content_client, telegram_id=300400)
    note = _create_indexed_content_object_with_source(
        content_client,
        headers,
        owner_user_id=owner_user_id,
        media_type="text",
        title="Hybrid metadata note",
        text="Hybrid metadata filter phrase in a plain note.",
        source_provider="web",
    )
    link = _create_indexed_content_object_with_source(
        content_client,
        headers,
        owner_user_id=owner_user_id,
        media_type="link",
        title="Hybrid metadata link",
        text="https://example.com/hybrid-metadata-filter",
        source_provider="telegram",
    )

    link_response = content_client.post(
        "/api/v1/search/hybrid",
        headers=headers,
        json={
            "query": "hybrid metadata",
            "limit": 10,
            "filters": {
                "content_type": "link",
                "content_source": "telegram",
            },
        },
    )
    note_response = content_client.post(
        "/api/v1/search/hybrid",
        headers=headers,
        json={
            "query": "hybrid metadata",
            "limit": 10,
            "filters": {
                "content_type": "note",
                "content_source": "web",
            },
        },
    )
    stale_date_response = content_client.post(
        "/api/v1/search/hybrid",
        headers=headers,
        json={
            "query": "hybrid metadata",
            "limit": 10,
            "filters": {
                "created_at_to": "2000-01-01T00:00:00+00:00",
            },
        },
    )

    assert link_response.status_code == 200, link_response.text
    assert {result["source_id"] for result in link_response.json()["results"]} == {
        link["id"]
    }
    assert link_response.json()["results"][0]["full_text_rank"] == 1
    assert note_response.status_code == 200, note_response.text
    assert {result["source_id"] for result in note_response.json()["results"]} == {
        note["id"]
    }
    assert stale_date_response.status_code == 200, stale_date_response.text
    assert stale_date_response.json()["results"] == []
