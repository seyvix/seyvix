from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from tests.test_content import TELEGRAM_BOT_TOKEN, _auth_headers


def _internal_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TELEGRAM_BOT_TOKEN}"}


def _ingest_text(
    client: TestClient,
    *,
    text: str,
    message_id: int,
    telegram_user_id: int = 100500,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/integrations/telegram/ingest",
        headers=_internal_headers(),
        data={
            "telegram_user_id": str(telegram_user_id),
            "telegram_chat_id": "9001",
            "telegram_message_id": str(message_id),
            "message_date": datetime.now(UTC).isoformat(),
            "material_type": "text",
            "text": text,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_telegram_ingest_requires_internal_token(content_client: TestClient) -> None:
    _auth_headers(content_client)

    response = content_client.post(
        "/api/v1/integrations/telegram/ingest",
        headers={"Authorization": "Bearer wrong-token"},
        data={
            "telegram_user_id": "100500",
            "telegram_chat_id": "9001",
            "telegram_message_id": "1",
            "material_type": "text",
            "text": "Draft",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_telegram_integration_token"


def test_telegram_ingest_rejects_unlinked_user(content_client: TestClient) -> None:
    response = content_client.post(
        "/api/v1/integrations/telegram/ingest",
        headers=_internal_headers(),
        data={
            "telegram_user_id": "404404",
            "telegram_chat_id": "9001",
            "telegram_message_id": "1",
            "material_type": "text",
            "text": "Draft",
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "telegram_user_not_linked"


def test_telegram_ingest_text_creates_markdown_note(content_client: TestClient) -> None:
    _auth_headers(content_client)

    payload = _ingest_text(
        content_client,
        text="## Research\n\nTelegram **markdown** body",
        message_id=1,
    )

    assert payload["status"] == "saved"
    assert payload["mode"] == "default"
    assert payload["note"]["type"] == "simple"
    assert payload["note"]["objects"][0]["type"] == "text"
    assert payload["note"]["objects"][0]["mimeType"] == "text/markdown"
    assert payload["note"]["objects"][0]["content"] == "## Research\n\nTelegram **markdown** body"


def test_telegram_default_mode_groups_fast_message_series(
    content_client: TestClient,
) -> None:
    _auth_headers(content_client)

    first = _ingest_text(content_client, text="First forwarded note", message_id=1)
    second = _ingest_text(content_client, text="Second forwarded note", message_id=2)

    assert first["note"]["type"] == "simple"
    assert second["status"] == "collection_updated"
    assert second["note"]["type"] == "collection"
    assert [obj["content"] for obj in second["note"]["objects"]] == [
        "First forwarded note",
        "Second forwarded note",
    ]


def test_telegram_mode_endpoint_switches_to_grouped_notes(
    content_client: TestClient,
) -> None:
    _auth_headers(content_client)

    response = content_client.post(
        "/api/v1/integrations/telegram/mode",
        headers=_internal_headers(),
        json={"telegram_user_id": "100500", "mode": "grouped_notes"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"mode": "grouped_notes"}
