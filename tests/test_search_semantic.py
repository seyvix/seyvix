import asyncio
import hashlib
import hmac
import os
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.database import build_session_factory
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
