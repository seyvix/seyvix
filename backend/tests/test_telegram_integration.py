from __future__ import annotations

from datetime import UTC, datetime
import json

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


def test_telegram_ingest_returns_universal_source_metadata(
    content_client: TestClient,
) -> None:
    _auth_headers(content_client)

    source = {
        "provider": "telegram",
        "provider_label": "Telegram",
        "external_id": "801627037:28",
        "original_created_at": datetime(2026, 5, 12, 10, 30, tzinfo=UTC).isoformat(),
        "origin": {
            "type": "user",
            "name": "Тёма",
            "username": "luvrikin",
        },
        "raw_payload": {"message_id": 28, "text": "да, давай так и сделаем"},
        "metadata": {"telegram_message_id": "28"},
    }

    response = content_client.post(
        "/api/v1/integrations/telegram/ingest",
        headers=_internal_headers(),
        data={
            "telegram_user_id": "100500",
            "telegram_chat_id": "801627037",
            "telegram_message_id": "28",
            "message_date": datetime.now(UTC).isoformat(),
            "material_type": "text",
            "text": "да, давай так и сделаем",
            "source": json.dumps(source),
        },
    )

    assert response.status_code == 201, response.text
    obj = response.json()["note"]["objects"][0]
    assert obj["source"]["provider"] == "telegram"
    assert obj["source"]["providerLabel"] == "Telegram"
    assert obj["source"]["origin"]["name"] == "Тёма"
    assert obj["source"]["origin"]["username"] == "luvrikin"
    assert obj["source"]["rawPayload"]["message_id"] == 28


def test_telegram_media_group_creates_single_collection_with_item_sources(
    content_client: TestClient,
) -> None:
    _auth_headers(content_client)

    def ingest_photo(message_id: int, original_message_id: int, caption: str | None) -> dict:
        source = {
            "provider": "telegram",
            "provider_label": "Telegram",
            "external_id": f"801627037:{message_id}",
            "group_id": "14227400699706618",
            "origin": {
                "type": "channel",
                "title": "Бэкдор",
                "username": "whackdoor",
                "url": f"https://t.me/whackdoor/{original_message_id}",
            },
            "metadata": {"telegram_message_id": str(message_id)},
            "raw_payload": {"message_id": message_id, "media_group_id": "14227400699706618"},
        }
        files = {
            "file": (
                f"telegram-photo-{message_id}.jpg",
                b"\xff\xd8\xff\xe0telegram-image\xff\xd9",
                "image/jpeg",
            )
        }
        response = content_client.post(
            "/api/v1/integrations/telegram/ingest",
            headers=_internal_headers(),
            data={
                "telegram_user_id": "100500",
                "telegram_chat_id": "801627037",
                "telegram_message_id": str(message_id),
                "message_date": datetime.now(UTC).isoformat(),
                "material_type": "photo",
                "caption": caption,
                "filename": f"telegram-photo-{message_id}.jpg",
                "mime_type": "image/jpeg",
                "source": json.dumps(source),
            },
            files=files,
        )
        assert response.status_code == 201, response.text
        return response.json()

    first = ingest_photo(29, 28305, "Caption from first album item")
    second = ingest_photo(30, 28306, None)

    assert first["note"]["type"] == "simple"
    assert second["status"] == "collection_updated"
    assert second["note"]["type"] == "collection"
    assert second["note"]["objects"][0]["caption"] == "Caption from first album item"
    assert [obj["source"]["origin"]["url"] for obj in second["note"]["objects"]] == [
        "https://t.me/whackdoor/28305",
        "https://t.me/whackdoor/28306",
    ]


def test_telegram_ingest_video_file_creates_video_note_object(
    content_client: TestClient,
) -> None:
    _auth_headers(content_client)

    response = content_client.post(
        "/api/v1/integrations/telegram/ingest",
        headers=_internal_headers(),
        data={
            "telegram_user_id": "100500",
            "telegram_chat_id": "801627037",
            "telegram_message_id": "42",
            "message_date": datetime.now(UTC).isoformat(),
            "material_type": "video",
            "caption": "Video from Telegram",
            "filename": "clip.mp4",
            "mime_type": "video/mp4",
        },
        files={"file": ("clip.mp4", b"fake-video", "video/mp4")},
    )

    assert response.status_code == 201, response.text
    objects = response.json()["note"]["objects"]
    video = next(obj for obj in objects if obj["type"] == "video")
    caption = next(obj for obj in objects if obj["type"] == "text")
    assert video["filename"] == "clip.mp4"
    assert video["mimeType"] == "video/mp4"
    assert caption["content"] == "Video from Telegram"


def test_telegram_ingest_voice_file_creates_audio_note_object(
    content_client: TestClient,
) -> None:
    _auth_headers(content_client)

    response = content_client.post(
        "/api/v1/integrations/telegram/ingest",
        headers=_internal_headers(),
        data={
            "telegram_user_id": "100500",
            "telegram_chat_id": "801627037",
            "telegram_message_id": "43",
            "message_date": datetime.now(UTC).isoformat(),
            "material_type": "voice",
            "filename": "telegram-voice.ogg",
            "mime_type": "audio/ogg",
        },
        files={"file": ("telegram-voice.ogg", b"fake-audio", "audio/ogg")},
    )

    assert response.status_code == 201, response.text
    obj = response.json()["note"]["objects"][0]
    assert obj["type"] == "audio"
    assert obj["filename"] == "telegram-voice.ogg"
    assert obj["mimeType"] == "audio/ogg"


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
