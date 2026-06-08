import asyncio
import hashlib
import hmac
import os
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import build_session_factory
from app.modules.content.models import ContentObject
from app.modules.content.models import ContentTag as LegacyContentTag
from app.modules.content.service import ContentService
from app.modules.search.infrastructure.meilisearch import (
    MeilisearchSearchBackend,
    build_meilisearch_filter_expression,
)
from app.modules.search.schemas import HybridSearchResult, SearchContentMatch, SearchFilters
from app.modules.search.service import SemanticSearchService, build_search_matches_by_source_id
from app.modules.vectorization.contracts import (
    VectorizedChunkFullTextSearchResult,
    VectorizedChunkSearchResult,
)
from app.modules.vectorization.worker import VectorizationWorker

TELEGRAM_BOT_TOKEN = "123456:test-bot-token"


def test_local_search_score_uses_legacy_content_tags() -> None:
    note = ContentObject(
        owner_user_id="user-1",
        slug="valheim-update",
        title="Patch notes",
        kind="single",
        media_type="text",
        storage_path="objects/valheim-update",
    )
    note.tags = [
        LegacyContentTag(
            owner_user_id="user-1",
            name="Viking survival game",
            slug="viking-survival-game",
        )
    ]

    assert (
        ContentService._local_search_score(
            note,
            "new game",
            active_tags=[],
            assignment=None,
        )
        > 0
    )
    assert (
        ContentService._local_search_score(
            note,
            "игра",
            active_tags=[],
            assignment=None,
        )
        > 0
    )

    recipe = ContentObject(
        owner_user_id="user-1",
        slug="new-recipe",
        title="New recipe update",
        kind="single",
        media_type="text",
        storage_path="objects/new-recipe",
    )

    assert (
        ContentService._local_search_score(
            recipe,
            "new game",
            active_tags=[],
            assignment=None,
        )
        == 0
    )


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


def _auth_session(client: TestClient, telegram_id: int = 100500) -> tuple[dict[str, str], str]:
    response = client.post("/api/v1/auth/telegram-login", json=_telegram_payload(telegram_id))
    assert response.status_code == 200, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, str(body["user"]["id"])


def _create_text_note(
    client: TestClient,
    headers: dict[str, str],
    *,
    title: str,
    text: str,
    folder_path: str | None = None,
    tag_names: list[str] | None = None,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/notes",
        headers=headers,
        json={
            "media_type": "text",
            "title": title,
            "text": text,
            "folder_path": folder_path,
            "tag_names": tag_names or [],
        },
    )
    assert response.status_code == 201
    return response.json()


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
    settings_response = client.patch(
        "/api/v1/taxonomy/settings",
        headers=headers,
        json={"category_profile_editing_enabled": True},
    )
    assert settings_response.status_code == 200, settings_response.text
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
        self.calls.append({"prompt": prompt, "schema": schema, "model_config": model_config})
        return {"queries": ["semantic retrieval", "postgres fts", "vector search"]}


class _FakeMeilisearchClient:
    def __init__(self) -> None:
        self.search_payloads: list[dict[str, Any]] = []

    async def search(self, *, index_uid: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.search_payloads.append({"index_uid": index_uid, "payload": payload})
        return {
            "hits": [
                {
                    "id": "chunk-1",
                    "source": "content",
                    "source_type": "content_object",
                    "source_id": "note-1",
                    "external_id": "content_object:note-1",
                    "chunk_external_id": "content_object:note-1:chunk:0",
                    "text": "Meilisearch hybrid result",
                    "metadata": {"media_type": "text"},
                    "_rankingScore": 0.75,
                }
            ]
        }


def test_meilisearch_filter_builder_scopes_owner_and_useful_metadata() -> None:
    expression = build_meilisearch_filter_expression(
        owner_user_id="user-1",
        filters=SearchFilters(
            content_types=["link", "pdf"],
            content_source="telegram",
            telegram_chat_type="group",
            telegram_chat_id="chat-42",
            telegram_author_id="author-7",
            tags=["ai", "research"],
            folder_path="work/research",
            created_at_from=datetime(2026, 5, 1, tzinfo=UTC),
            created_at_to=datetime(2026, 5, 31, 23, 59, tzinfo=UTC),
        ),
        source="content",
        source_type="content_object",
        source_id=None,
    )

    assert expression == (
        'owner_user_id = "user-1" AND source = "content" AND '
        'source_type = "content_object" AND (content_type = "link" OR content_type = "pdf") '
        'AND source_provider = "telegram" AND telegram_chat_type = "group" '
        'AND telegram_chat_id = "chat-42" AND telegram_author_id = "author-7" '
        'AND tags = "ai" AND tags = "research" AND folder_path = "work/research" '
        "AND content_created_ts >= 1777593600 AND content_created_ts <= 1780271940"
    )


def test_search_matches_group_content_chunks_and_highlight_query_terms() -> None:
    results = [
        HybridSearchResult(
            source="content",
            source_type="content_object",
            source_id="note-1",
            external_id="content_object:note-1",
            chunk_id="chunk-1",
            chunk_external_id="content_object:note-1:chunk:0",
            text="A semantic chunk finds Vector search inside the saved note.",
            metadata={"media_type": "text"},
            score=0.9,
        ),
        HybridSearchResult(
            source="content",
            source_type="content_object",
            source_id="note-1",
            external_id="content_object:note-1",
            chunk_id="chunk-2",
            chunk_external_id="content_object:note-1:chunk:1",
            text="A second matching passage for vector retrieval.",
            metadata={"media_type": "text"},
            score=0.7,
        ),
        HybridSearchResult(
            source="taxonomy",
            source_type="category_profile",
            source_id="category-1",
            external_id="taxonomy_category_profile:category-1",
            chunk_id="chunk-3",
            chunk_external_id="taxonomy_category_profile:category-1:chunk:0",
            text="Ignored taxonomy result.",
            metadata={},
            score=0.95,
        ),
    ]

    matches = build_search_matches_by_source_id(
        query="vector search",
        results=results,
        max_matches_per_note=1,
    )

    assert list(matches) == ["note-1"]
    assert len(matches["note-1"]) == 1
    assert matches["note-1"][0].text == results[0].text
    highlighted = [
        results[0].text[item.start : item.end] for item in matches["note-1"][0].highlight_ranges
    ]
    assert highlighted == ["Vector", "search"]


@pytest.mark.asyncio
async def test_meilisearch_backend_uses_selected_search_mode() -> None:
    client = _FakeMeilisearchClient()
    embeddings = _FakeEmbeddingProvider()
    backend = MeilisearchSearchBackend(
        client=client,
        embedding_provider=embeddings,
        settings=Settings(
            search_meilisearch_index_uid="content_chunks",
            search_meilisearch_embedder="content",
            vector_embedding_dimensions=3,
        ),
    )

    await backend.search(
        owner_user_id="user-1",
        query="hybrid typo",
        limit=5,
        mode="full_text",
        filters=SearchFilters(content_source="telegram"),
    )
    await backend.search(
        owner_user_id="user-1",
        query="hybrid typo",
        limit=5,
        mode="semantic",
        filters=SearchFilters(content_source="telegram"),
    )
    await backend.search(
        owner_user_id="user-1",
        query="hybrid typo",
        limit=5,
        mode="hybrid",
        filters=SearchFilters(content_source="telegram"),
    )

    full_text_payload = client.search_payloads[0]["payload"]
    semantic_payload = client.search_payloads[1]["payload"]
    hybrid_full_text_payload = client.search_payloads[2]["payload"]
    hybrid_semantic_payload = client.search_payloads[3]["payload"]

    assert full_text_payload["q"] == "hybrid typo"
    assert full_text_payload["showRankingScore"] is True
    assert full_text_payload["matchingStrategy"] == "all"
    assert "vector" not in full_text_payload
    assert "hybrid" not in full_text_payload
    assert "rankingScoreThreshold" not in full_text_payload
    assert semantic_payload["vector"] == [1.0, 1.0, 1.0]
    assert semantic_payload["hybrid"] == {
        "embedder": "content",
        "semanticRatio": 1.0,
    }
    assert hybrid_full_text_payload["matchingStrategy"] == "all"
    assert "vector" not in hybrid_full_text_payload
    assert "hybrid" not in hybrid_full_text_payload
    assert hybrid_semantic_payload["vector"] == [1.0, 1.0, 1.0]
    assert hybrid_semantic_payload["hybrid"] == {
        "embedder": "content",
        "semanticRatio": 1.0,
    }


@pytest.mark.asyncio
async def test_meilisearch_hybrid_prioritizes_strong_full_text_over_semantic_only() -> None:
    class _PriorityClient:
        async def search(self, *, index_uid: str, payload: dict[str, Any]) -> dict[str, Any]:
            if "vector" in payload:
                return {
                    "hits": [
                        {
                            "id": "semantic-chunk",
                            "source": "content",
                            "source_type": "content_object",
                            "source_id": "semantic-note",
                            "external_id": "content_object:semantic-note",
                            "chunk_external_id": "content_object:semantic-note:chunk:0",
                            "text": "Semantic-only result with a high vector score.",
                            "metadata": {"media_type": "text"},
                            "_rankingScore": 0.99,
                        },
                        {
                            "id": "weak-semantic-chunk",
                            "source": "content",
                            "source_type": "content_object",
                            "source_id": "weak-semantic-note",
                            "external_id": "content_object:weak-semantic-note",
                            "chunk_external_id": "content_object:weak-semantic-note:chunk:0",
                            "text": "Weak semantic-only result below the hybrid cutoff.",
                            "metadata": {"media_type": "text"},
                            "_rankingScore": 0.7,
                        },
                    ]
                }
            return {
                "hits": [
                    {
                        "id": "full-text-chunk",
                        "source": "content",
                        "source_type": "content_object",
                        "source_id": "full-text-note",
                        "external_id": "content_object:full-text-note",
                        "chunk_external_id": "content_object:full-text-note:chunk:0",
                        "text": "Full-text result that passes the confidence threshold.",
                        "metadata": {"media_type": "text"},
                        "_rankingScore": 0.63,
                    }
                ]
            }

    backend = MeilisearchSearchBackend(
        client=cast(Any, _PriorityClient()),
        embedding_provider=_FakeEmbeddingProvider(),
        settings=Settings(
            search_meilisearch_hybrid_semantic_ratio=0.35,
            search_meilisearch_ranking_score_threshold=0.6,
            search_meilisearch_hybrid_semantic_only_threshold=0.85,
            vector_embedding_dimensions=3,
        ),
    )

    results = await backend.search(
        owner_user_id="user-1",
        query="important words",
        limit=10,
        mode="hybrid",
        filters=None,
    )

    assert [result.chunk_id for result in results] == ["full-text-chunk", "semantic-chunk"]
    assert results[0].full_text_score == 0.63
    assert results[1].vector_score == 0.99


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
    assert embeddings.text_batches == [["vector search", "semantic retrieval", "postgres fts"]]
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
    assert body["results"][0]["external_id"] == f"taxonomy_category_profile:{category['id']}"
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
    assert {result["source"] for result in taxonomy_only.json()["results"]} == {"taxonomy"}
    assert taxonomy_only.json()["results"][0]["source_id"] == taxonomy_category["id"]
    assert content_only.status_code == 200, content_only.text
    assert {result["source"] for result in content_only.json()["results"]} == {"content"}
    assert one_source.status_code == 200, one_source.text
    assert {result["source_id"] for result in one_source.json()["results"]} == {content_note["id"]}


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
    assert {result["source_id"] for result in link_response.json()["results"]} == {link["id"]}
    assert link_response.json()["results"][0]["full_text_rank"] == 1
    assert note_response.status_code == 200, note_response.text
    assert {result["source_id"] for result in note_response.json()["results"]} == {note["id"]}
    assert stale_date_response.status_code == 200, stale_date_response.text
    assert stale_date_response.json()["results"] == []


@pytest.mark.asyncio
async def test_http_client_replace_documents_pins_primary_key_to_id() -> None:
    """
    The chunk document schema contains many `*_id` fields (chunk_external_id,
    content_object_id, source_id, ...). Meilisearch cannot infer a primary key
    from that, so it rejects every `documentAdditionOrUpdate` task. The client
    must pin `primaryKey=id` on the POST so Meilisearch uses our canonical id.
    """
    from app.modules.search.infrastructure.meilisearch import HttpMeilisearchClient

    captured: dict[str, object] = {}

    class _StubTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["method"] = request.method
            return httpx.Response(202, json={"taskUid": 1})

    real_async_client = httpx.AsyncClient

    def _patched_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = _StubTransport()
        return real_async_client(*args, **kwargs)

    import app.modules.search.infrastructure.meilisearch as meili_mod

    monkey_target = "httpx.AsyncClient"
    original = meili_mod.httpx.AsyncClient
    meili_mod.httpx.AsyncClient = _patched_client  # type: ignore[assignment]
    try:
        client = HttpMeilisearchClient(
            base_url="http://meilisearch:7700",
            api_key=None,
            timeout_seconds=5,
        )
        await client.replace_documents(
            index_uid="content_chunks",
            documents=[{"id": "abc", "text": "hello"}],
        )
    finally:
        meili_mod.httpx.AsyncClient = original  # type: ignore[assignment]
    assert monkey_target  # noqa: B015 — keeps the variable used for readability

    assert captured["method"] == "POST"
    url = str(captured["url"])
    assert "primaryKey=id" in url, f"primary key not pinned in URL: {url}"


@pytest.mark.asyncio
async def test_meilisearch_backend_filters_ranking_scores_client_side() -> None:
    """
    Meilisearch provides `_rankingScore` when `showRankingScore` is enabled.
    The application owns the confidence cutoff so an unrelated query can
    intentionally return an empty or partial result set.
    """

    class _CapturingClient:
        def __init__(self) -> None:
            self.payloads: list[dict[str, Any]] = []

        async def search(self, *, index_uid: str, payload: dict[str, Any]) -> dict[str, Any]:
            self.payloads.append(payload)
            return {
                "hits": [
                    {
                        "id": "strong-chunk",
                        "source": "content",
                        "source_type": "content_object",
                        "source_id": "strong-note",
                        "external_id": "content_object:strong-note",
                        "chunk_external_id": "content_object:strong-note:chunk:0",
                        "text": "Strong enough full-text result.",
                        "metadata": {"media_type": "text"},
                        "_rankingScore": 0.75,
                    },
                    {
                        "id": "weak-chunk",
                        "source": "content",
                        "source_type": "content_object",
                        "source_id": "weak-note",
                        "external_id": "content_object:weak-note",
                        "chunk_external_id": "content_object:weak-note:chunk:0",
                        "text": "Weak result below the confidence threshold.",
                        "metadata": {"media_type": "text"},
                        "_rankingScore": 0.2,
                    },
                ]
            }

        async def configure_index(self, **kwargs: Any) -> None:
            return None

        async def replace_documents(self, **kwargs: Any) -> None:
            return None

        async def delete_documents_by_filter(self, **kwargs: Any) -> None:
            return None

    class _StubEmbeddingProvider:
        async def embed_texts(
            self, texts: list[str], *, model: str, dimensions: int
        ) -> list[list[float]]:
            return [[0.0] * dimensions for _ in texts]

    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        auth_jwt_secret="test-secret",
        search_engine="meilisearch",
        search_meilisearch_url="http://meilisearch:7700",
        search_meilisearch_ranking_score_threshold=0.62,
        vector_embedding_dimensions=4,
    )
    client = _CapturingClient()
    backend = MeilisearchSearchBackend(
        client=cast(Any, client),
        embedding_provider=cast(Any, _StubEmbeddingProvider()),
        settings=settings,
    )

    results = await backend.search(
        owner_user_id="user-1",
        query="anything",
        limit=10,
        mode="full_text",
        filters=None,
        source="content",
        source_type="content_object",
    )

    assert len(client.payloads) == 1
    assert client.payloads[0]["showRankingScore"] is True
    assert "rankingScoreThreshold" not in client.payloads[0]
    assert [result.chunk_id for result in results] == ["strong-chunk"]


@pytest.mark.asyncio
async def test_count_owned_notes_excludes_collections_and_trash() -> None:
    """
    The threshold uses a count visible to the user: live notes only.
    Collections are containers, not notes; trashed items are not on the
    dashboard. Other users' notes must not leak into the count.
    """
    from datetime import UTC, datetime

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.database import Base
    from app.modules.auth.models import User
    from app.modules.content.infrastructure.repositories import ContentRepository
    from app.modules.content.models import ContentObject

    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run database-backed tests.")

    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()
    factory = build_session_factory(database_url)

    async with factory() as session:
        repo = ContentRepository(session)
        now = datetime.now(UTC)
        owner = "u-owner"
        other = "u-other"
        session.add_all(
            [
                User(id=owner, telegram_id="100501", display_name="Owner"),
                User(id=other, telegram_id="100502", display_name="Other"),
            ]
        )
        kept = [
            ContentObject(
                id=f"obj-kept-{i}",
                owner_user_id=owner,
                slug=f"kept-{i}",
                title=f"Kept {i}",
                kind="simple",
                media_type="text",
                storage_path=f"content-assets/obj-kept-{i}",
                sort_order=i,
                created_at=now,
                updated_at=now,
            )
            for i in range(3)
        ]
        collection = ContentObject(
            id="obj-collection",
            owner_user_id=owner,
            slug="collection",
            title="Album",
            kind="collection",
            media_type=None,
            storage_path="content-assets/obj-collection",
            sort_order=10,
            created_at=now,
            updated_at=now,
        )
        trashed = ContentObject(
            id="obj-trashed",
            owner_user_id=owner,
            slug="trashed",
            title="Trashed",
            kind="simple",
            media_type="text",
            storage_path="content-assets/obj-trashed",
            sort_order=11,
            created_at=now,
            updated_at=now,
            deleted_at=now,
        )
        foreign = ContentObject(
            id="obj-foreign",
            owner_user_id=other,
            slug="foreign",
            title="Foreign",
            kind="simple",
            media_type="text",
            storage_path="content-assets/obj-foreign",
            sort_order=12,
            created_at=now,
            updated_at=now,
        )
        session.add_all([*kept, collection, trashed, foreign])
        await session.commit()
        assert await repo.count_owned_notes(owner_user_id=owner) == 3


def test_search_capabilities_below_threshold_only_full_text(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    # Override threshold via the settings cache so this test doesn't depend on env
    settings = get_settings()
    settings.search_vector_modes_min_notes = 3
    settings.search_engine = "meilisearch"
    settings.search_meilisearch_url = "http://meilisearch:7700"

    _create_text_note(content_client, headers, title="A", text="alpha")
    _create_text_note(content_client, headers, title="B", text="beta")

    response = content_client.get("/api/v1/search/capabilities", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["noteCount"] == 2
    assert body["threshold"] == 3
    assert body["unlockedModes"] == ["full_text"]
    assert body["defaultMode"] == "full_text"


def test_search_capabilities_default_unlocks_vector_modes_for_small_note_sets(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    settings = get_settings()
    settings.search_vector_modes_min_notes = 0
    settings.search_engine = "meilisearch"
    settings.search_meilisearch_url = "http://meilisearch:7700"

    _create_text_note(content_client, headers, title="A", text="alpha")

    response = content_client.get("/api/v1/search/capabilities", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["noteCount"] == 1
    assert body["threshold"] == 0
    assert body["unlockedModes"] == ["full_text", "semantic", "hybrid"]
    assert body["defaultMode"] == "hybrid"


def test_search_capabilities_above_threshold_unlocks_vector_modes(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    settings = get_settings()
    settings.search_vector_modes_min_notes = 2
    settings.search_engine = "meilisearch"
    settings.search_meilisearch_url = "http://meilisearch:7700"

    _create_text_note(content_client, headers, title="A", text="alpha")
    _create_text_note(content_client, headers, title="B", text="beta")

    response = content_client.get("/api/v1/search/capabilities", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["noteCount"] == 2
    assert body["unlockedModes"] == ["full_text", "semantic", "hybrid"]
    assert body["defaultMode"] == "hybrid"


def test_search_capabilities_without_meilisearch_offers_only_full_text(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    settings = get_settings()
    settings.search_vector_modes_min_notes = 0  # would otherwise unlock
    settings.search_engine = "postgres"
    settings.search_meilisearch_url = None

    response = content_client.get("/api/v1/search/capabilities", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["unlockedModes"] == ["full_text"]
    assert body["defaultMode"] == "full_text"


def test_list_notes_downgrades_locked_mode_silently(
    content_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    An old client (or a stale tab) could still send search_mode=hybrid
    after the user dropped below the threshold. The backend must serve
    full_text results instead of refusing — no 4xx — and log it.
    """
    headers = _auth_headers(content_client)
    settings = get_settings()
    settings.search_vector_modes_min_notes = 5
    settings.search_engine = "meilisearch"
    settings.search_meilisearch_url = "http://meilisearch:7700"

    # Capture the mode actually used to query content
    used_mode: list[str] = []

    async def fake_search(self, *, owner_user_id, query, limit, mode, filters):  # type: ignore[no-untyped-def]
        used_mode.append(mode)
        return {}

    monkeypatch.setattr(
        "app.modules.search.service.SemanticSearchService." "search_content_object_matches",
        fake_search,
    )

    _create_text_note(content_client, headers, title="A", text="alpha")

    response = content_client.get(
        "/api/v1/notes",
        headers=headers,
        params={"search": "alpha", "search_mode": "hybrid"},
    )
    assert response.status_code == 200
    assert used_mode == ["full_text"]


def test_list_notes_keeps_empty_meilisearch_result_set(
    content_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _auth_headers(content_client)
    settings = get_settings()
    settings.search_vector_modes_min_notes = 0
    settings.search_engine = "meilisearch"
    settings.search_meilisearch_url = "http://meilisearch:7700"

    async def fake_search(self, *, owner_user_id, query, limit, mode, filters):  # type: ignore[no-untyped-def]
        return {}

    monkeypatch.setattr(
        "app.modules.search.service.SemanticSearchService." "search_content_object_matches",
        fake_search,
    )

    _create_text_note(content_client, headers, title="A", text="alpha")

    response = content_client.get(
        "/api/v1/notes",
        headers=headers,
        params={"search": "alpha", "search_mode": "full_text"},
    )

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_list_notes_hybrid_falls_back_to_local_tag_matches_when_meilisearch_is_empty(
    content_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _auth_headers(content_client)
    settings = get_settings()
    settings.search_vector_modes_min_notes = 0
    settings.search_engine = "meilisearch"
    settings.search_meilisearch_url = "http://meilisearch:7700"

    async def fake_search(self, *, owner_user_id, query, limit, mode, filters):  # type: ignore[no-untyped-def]
        return {}

    monkeypatch.setattr(
        "app.modules.search.service.SemanticSearchService." "search_content_object_matches",
        fake_search,
    )

    valheim = _create_text_note(
        content_client,
        headers,
        title="Valheim 1.0 release",
        text="A large survival update with a northern biome.",
        tag_names=["Game update", "New biome", "Viking survival game"],
    )
    stronghold = _create_text_note(
        content_client,
        headers,
        title="Stronghold 4 announced",
        text="A medieval strategy sequel trailer.",
        tag_names=["Game update", "real-time strategy"],
    )
    _create_text_note(
        content_client,
        headers,
        title="New recipe",
        text="A new dinner recipe with no entertainment context.",
        tag_names=[],
    )

    response = content_client.get(
        "/api/v1/notes",
        headers=headers,
        params={"search": "new game", "search_mode": "hybrid"},
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["id"] for item in items] == [stronghold["id"], valheim["id"]]


def test_list_notes_hybrid_prioritizes_local_matches_before_semantic_only_results(
    content_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _auth_headers(content_client)
    settings = get_settings()
    settings.search_vector_modes_min_notes = 0
    settings.search_engine = "meilisearch"
    settings.search_meilisearch_url = "http://meilisearch:7700"

    game_note = _create_text_note(
        content_client,
        headers,
        title="Valheim 1.0 release",
        text="A survival update with a new biome.",
        tag_names=["Game update", "New biome", "Viking survival game"],
    )
    semantic_only = _create_text_note(
        content_client,
        headers,
        title="Habr article",
        text="A backend indexing article.",
        tag_names=["backend"],
    )

    async def fake_search(self, *, owner_user_id, query, limit, mode, filters):  # type: ignore[no-untyped-def]
        return {
            semantic_only["id"]: [
                SearchContentMatch(
                    chunk_id="semantic-only",
                    chunk_external_id="content_object:semantic-only:chunk:0",
                    text="A semantically similar but lexically unrelated article.",
                    score=0.99,
                    highlight_ranges=[],
                )
            ]
        }

    monkeypatch.setattr(
        "app.modules.search.service.SemanticSearchService." "search_content_object_matches",
        fake_search,
    )

    response = content_client.get(
        "/api/v1/notes",
        headers=headers,
        params={"search": "new game", "search_mode": "hybrid"},
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["id"] for item in items] == [game_note["id"], semantic_only["id"]]


def test_list_notes_passes_extended_filter_params_to_search_service(
    content_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _auth_headers(content_client)
    settings = get_settings()
    settings.search_vector_modes_min_notes = 0
    settings.search_engine = "meilisearch"
    settings.search_meilisearch_url = "http://meilisearch:7700"

    captured_filters: list[SearchFilters] = []

    async def fake_search(self, *, owner_user_id, query, limit, mode, filters):  # type: ignore[no-untyped-def]
        captured_filters.append(filters)
        return {}

    monkeypatch.setattr(
        "app.modules.search.service.SemanticSearchService." "search_content_object_matches",
        fake_search,
    )

    _create_text_note(content_client, headers, title="A", text="alpha")

    response = content_client.get(
        "/api/v1/notes",
        headers=headers,
        params={
            "search": "alpha",
            "search_mode": "hybrid",
            "types": ["video", "pdf"],
            "sources": ["telegram"],
            "favorite": "true",
            "created_after": "2026-05-01T00:00:00+00:00",
            "created_before": "2026-06-01T00:00:00+00:00",
        },
    )

    assert response.status_code == 200
    assert len(captured_filters) == 1
    filters = captured_filters[0]
    assert filters.content_types == ["video", "pdf"]
    assert filters.source_provider == "telegram"
    assert filters.is_favorite is True
    assert filters.created_at_from == datetime(2026, 5, 1, tzinfo=UTC)
    assert filters.created_at_to == datetime(2026, 6, 1, tzinfo=UTC)
