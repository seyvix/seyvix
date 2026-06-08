import asyncio
import hashlib
import hmac
import os
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import build_session_factory
from app.modules.content.models import ContentObject
from app.modules.vectorization.models import (
    VectorizationChunk,
    VectorizationDocument,
    VectorizationEmbedding,
    VectorizationSource,
)

TELEGRAM_BOT_TOKEN = "123456:test-bot-token"
VECTOR_DIMENSIONS = 384


@pytest.fixture(autouse=True)
def _recommendation_vector_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("VECTOR_EMBEDDING_PROVIDER", "fake")
    monkeypatch.setenv("VECTOR_EMBEDDING_MODEL", "fake-embedding")
    monkeypatch.setenv("VECTOR_EMBEDDING_DIMENSIONS", str(VECTOR_DIMENSIONS))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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


def _create_text_note(
    client: TestClient,
    headers: dict[str, str],
    *,
    title: str,
    text: str,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/notes",
        headers=headers,
        json={"media_type": "text", "title": title, "text": text},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _worker_session_factory():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run DB-backed recommendation tests.")
    return build_session_factory(database_url)


def _vector(first: float, second: float) -> list[float]:
    return [first, second, *([0.0] * (VECTOR_DIMENSIONS - 2))]


async def _insert_vectorized_notes(vectors_by_note_id: dict[str, list[float]]) -> None:
    session_factory = _worker_session_factory()
    now = datetime.now(UTC)
    async with session_factory() as session:
        for note_id, vector in vectors_by_note_id.items():
            content_object = await session.scalar(
                select(ContentObject).where(ContentObject.id == note_id)
            )
            assert content_object is not None
            source = VectorizationSource(
                owner_user_id=content_object.owner_user_id,
                source="content",
                source_type="content_object",
                source_id=content_object.id,
                external_id=f"content_object:{content_object.id}",
                source_hash=f"hash:{content_object.id}",
                status="synced",
                provider="fake",
                model="fake-embedding",
                dimensions=VECTOR_DIMENSIONS,
                last_indexed_at=now,
            )
            session.add(source)
            await session.flush()
            document = VectorizationDocument(
                owner_user_id=content_object.owner_user_id,
                source_record_id=source.id,
                external_id=source.external_id,
                text=f"Title: {content_object.title}\nContent:\n{content_object.title}",
                text_hash=f"document:{content_object.id}",
                metadata_={"content_object_id": content_object.id},
                chunking_strategy="plain-text",
                representation_type="content_object",
            )
            session.add(document)
            await session.flush()
            chunk = VectorizationChunk(
                owner_user_id=content_object.owner_user_id,
                source_record_id=source.id,
                document_id=document.id,
                chunk_index=0,
                chunk_external_id=f"content_object:{content_object.id}:0",
                text=f"Matched text for {content_object.title}",
                text_hash=f"chunk:{content_object.id}",
                token_count=8,
                metadata_={"content_object_id": content_object.id},
            )
            session.add(chunk)
            await session.flush()
            session.add(
                VectorizationEmbedding(
                    owner_user_id=content_object.owner_user_id,
                    chunk_id=chunk.id,
                    provider="fake",
                    model="fake-embedding",
                    dimensions=VECTOR_DIMENSIONS,
                    embedding=vector,
                    embedding_hash=f"embedding:{content_object.id}",
                )
            )
        await session.commit()


def test_note_recommendations_search_across_user_database_and_filter_invisible_notes(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client, telegram_id=450100)
    other_headers = _auth_headers(content_client, telegram_id=450200)
    target = _create_text_note(
        content_client,
        headers,
        title="Vector databases",
        text="Notes about HNSW, embeddings, and semantic retrieval.",
    )
    related = _create_text_note(
        content_client,
        headers,
        title="Semantic search guide",
        text="Embedding indexes and vector retrieval notes.",
    )
    unrelated = _create_text_note(
        content_client,
        headers,
        title="Travel checklist",
        text="Tickets, hotels, and personal planning.",
    )
    deleted = _create_text_note(
        content_client,
        headers,
        title="Deleted semantic draft",
        text="A deleted note that would otherwise be closest.",
    )
    other_user_note = _create_text_note(
        content_client,
        other_headers,
        title="Other user vector note",
        text="This belongs to another user.",
    )

    delete_response = content_client.request(
        "DELETE",
        "/api/v1/notes",
        headers=headers,
        json={"slugs": [deleted["slug"]]},
    )
    assert delete_response.status_code == 204, delete_response.text

    asyncio.run(
        _insert_vectorized_notes(
            {
                str(target["id"]): _vector(1.0, 0.0),
                str(related["id"]): _vector(0.99, 0.05),
                str(unrelated["id"]): _vector(0.0, 1.0),
                str(deleted["id"]): _vector(1.0, 0.0),
                str(other_user_note["id"]): _vector(1.0, 0.0),
            }
        )
    )

    response = content_client.get(
        f"/api/v1/notes/{target['slug']}/recommendations?limit=2",
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    titles = [item["title"] for item in payload["items"]]
    assert titles[0] == "Semantic search guide"
    assert "Vector databases" not in titles
    assert "Deleted semantic draft" not in titles
    assert "Other user vector note" not in titles
    assert payload["items"][0]["matched_text"] == "Matched text for Semantic search guide"


def test_note_recommendations_limit_is_clamped_to_five_and_allows_smaller_values(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client, telegram_id=450300)
    target = _create_text_note(
        content_client,
        headers,
        title="Recommendation seed",
        text="Seed note about embeddings.",
    )
    candidates = [
        _create_text_note(
            content_client,
            headers,
            title=f"Candidate {index}",
            text=f"Candidate note {index} about embeddings.",
        )
        for index in range(1, 7)
    ]

    asyncio.run(
        _insert_vectorized_notes(
            {
                str(target["id"]): _vector(1.0, 0.0),
                **{
                    str(candidate["id"]): _vector(1.0, index / 100)
                    for index, candidate in enumerate(candidates, start=1)
                },
            }
        )
    )

    clamped_response = content_client.get(
        f"/api/v1/notes/{target['slug']}/recommendations?limit=99",
        headers=headers,
    )
    smaller_response = content_client.get(
        f"/api/v1/notes/{target['slug']}/recommendations?limit=3",
        headers=headers,
    )

    assert clamped_response.status_code == 200, clamped_response.text
    assert smaller_response.status_code == 200, smaller_response.text
    assert len(clamped_response.json()["items"]) == 5
    assert len(smaller_response.json()["items"]) == 3
