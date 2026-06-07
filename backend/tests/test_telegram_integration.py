from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.modules.content.schemas import NoteAssetResponse, NoteCardResponse, SourceMetadataResponse
from app.modules.content.service import ContentService, UploadedContent
from app.modules.telegram_integration.schemas import TelegramIngestPayload
from app.modules.telegram_integration.service import TelegramIngestService
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


def test_telegram_media_only_title_ignores_transport_filename() -> None:
    title = TelegramIngestService._title(
        payload=TelegramIngestPayload(
            telegram_user_id="100500",
            telegram_chat_id="801627037",
            telegram_message_id="41",
            material_type="photo",
            filename="telegram-photo-41.jpg",
            mime_type="image/jpeg",
        ),
        uploaded=UploadedContent(
            filename="telegram-photo-41.jpg",
            content_type="image/jpeg",
            data=b"\xff\xd8\xff\xe0telegram-image\xff\xd9",
        ),
        text=None,
    )

    assert title == ""


def test_telegram_batch_media_only_title_ignores_transport_filename() -> None:
    payloads = [
        TelegramIngestPayload(
            telegram_user_id="100500",
            telegram_chat_id="801627037",
            telegram_message_id="42",
            material_type="video",
            filename="telegram-video-42.mp4",
            mime_type="video/mp4",
        ),
    ]
    title = TelegramIngestService._batch_title(
        payloads=payloads,
        uploaded=[
            UploadedContent(
                filename="telegram-video-42.mp4",
                content_type="video/mp4",
                data=b"fake-video",
            )
        ],
        text=TelegramIngestService._batch_text(payloads),
    )

    assert title == ""


def test_telegram_batch_text_deduplicates_caption_parts() -> None:
    payloads = [
        TelegramIngestPayload(
            telegram_user_id="100500",
            telegram_chat_id="801627037",
            telegram_message_id="42",
            material_type="video",
            caption="Shared caption",
        ),
        TelegramIngestPayload(
            telegram_user_id="100500",
            telegram_chat_id="801627037",
            telegram_message_id="43",
            material_type="photo",
            caption="Shared caption",
        ),
        TelegramIngestPayload(
            telegram_user_id="100500",
            telegram_chat_id="801627037",
            telegram_message_id="44",
            material_type="text",
            text="Second text",
        ),
    ]

    assert TelegramIngestService._batch_text(payloads) == "Shared caption\n\nSecond text"


def test_telegram_batch_source_targets_keep_first_source_as_object_fallback() -> None:
    created_at = datetime.now(UTC)
    first = TelegramIngestPayload(
        telegram_user_id="100500",
        telegram_chat_id="801627037",
        telegram_message_id="51",
        material_type="photo",
        caption="Shared caption",
        source={
            "provider": "telegram",
            "provider_label": "Telegram",
            "external_id": "801627037:51",
        },
    )
    second = TelegramIngestPayload(
        telegram_user_id="100500",
        telegram_chat_id="801627037",
        telegram_message_id="52",
        material_type="video",
        source={
            "provider": "telegram",
            "provider_label": "Telegram",
            "external_id": "801627037:52",
        },
    )
    card = NoteCardResponse(
        id="note-1",
        slug="telegram-batch",
        kind="complex",
        media_type="image",
        title="Telegram batch",
        source_filename="first.jpg",
        taxonomy_category=None,
        tags=[],
        is_favorite=False,
        sort_order=0,
        created_at=created_at,
        updated_at=created_at,
        download_url="/api/v1/notes/telegram-batch/download",
        assets=[
            NoteAssetResponse(
                id="asset-text",
                role="text",
                media_type="text",
                filename="content.md",
                mime_type="text/markdown",
                size_bytes=14,
            ),
            NoteAssetResponse(
                id="asset-image",
                role="original",
                media_type="image",
                filename="first.jpg",
                mime_type="image/jpeg",
                size_bytes=10,
            ),
            NoteAssetResponse(
                id="asset-video",
                role="original",
                media_type="video",
                filename="second.mp4",
                mime_type="video/mp4",
                size_bytes=10,
            ),
        ],
    )

    targets = TelegramIngestService._batch_source_targets(
        card=card,
        payloads=[first, second],
        uploaded=[
            UploadedContent(filename="first.jpg", content_type="image/jpeg", data=b"image"),
            UploadedContent(filename="second.mp4", content_type="video/mp4", data=b"video"),
        ],
    )

    assert [(payload.source.external_id, asset_id) for payload, asset_id in targets] == [
        ("801627037:51", None),
        ("801627037:52", "asset-video"),
    ]


def test_telegram_batch_source_targets_use_upload_order_for_duplicate_names() -> None:
    created_at = datetime.now(UTC)
    first = TelegramIngestPayload(
        telegram_user_id="100500",
        telegram_chat_id="801627037",
        telegram_message_id="51",
        material_type="photo",
        source={
            "provider": "telegram",
            "provider_label": "Telegram",
            "external_id": "801627037:51",
        },
    )
    second = TelegramIngestPayload(
        telegram_user_id="100500",
        telegram_chat_id="801627037",
        telegram_message_id="52",
        material_type="photo",
        source={
            "provider": "telegram",
            "provider_label": "Telegram",
            "external_id": "801627037:52",
        },
    )
    card = NoteCardResponse(
        id="note-1",
        slug="telegram-batch",
        kind="complex",
        media_type="image",
        title="Telegram batch",
        source_filename="telegram-photo.jpg",
        taxonomy_category=None,
        tags=[],
        is_favorite=False,
        sort_order=0,
        created_at=created_at,
        updated_at=created_at,
        download_url="/api/v1/notes/telegram-batch/download",
        assets=[
            NoteAssetResponse(
                id="asset-first",
                role="original",
                media_type="image",
                filename="telegram-photo.jpg",
                mime_type="image/jpeg",
                size_bytes=10,
            ),
            NoteAssetResponse(
                id="asset-second",
                role="original",
                media_type="image",
                filename="telegram-photo.jpg",
                mime_type="image/jpeg",
                size_bytes=10,
            ),
        ],
    )

    targets = TelegramIngestService._batch_source_targets(
        card=card,
        payloads=[first, second],
        uploaded=[
            UploadedContent(filename="telegram-photo.jpg", content_type="image/jpeg", data=b"1"),
            UploadedContent(filename="telegram-photo.jpg", content_type="image/jpeg", data=b"2"),
        ],
    )

    assert [(payload.source.external_id, asset_id) for payload, asset_id in targets] == [
        ("801627037:51", None),
        ("801627037:52", "asset-second"),
    ]


def test_telegram_source_metadata_merges_custom_emoji_assets_from_later_sources() -> None:
    first = SourceMetadataResponse(
        provider="telegram",
        provider_label="Telegram",
        external_id="801627037:51",
        metadata={"telegram_message_id": "51"},
    )
    second = SourceMetadataResponse(
        provider="telegram",
        provider_label="Telegram",
        external_id="801627037:52",
        custom_emoji_ids=["5280586677532774817"],
        metadata={
            "telegram_message_id": "52",
            "custom_emoji_assets": {
                "5280586677532774817": {
                    "data_url": "data:image/webp;base64,emoji",
                    "fallback": "⚡️",
                }
            },
        },
    )

    merged = ContentService._merge_source_metadata(first, [first, second])

    assert merged.external_id == "801627037:51"
    assert merged.custom_emoji_ids == ["5280586677532774817"]
    assert merged.metadata["telegram_message_id"] == "51"
    assert merged.metadata["custom_emoji_assets"] == {
        "5280586677532774817": {
            "data_url": "data:image/webp;base64,emoji",
            "fallback": "⚡️",
        }
    }
    assert "custom_emoji_assets" not in first.metadata


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


def test_telegram_status_returns_linked_user_context(content_client: TestClient) -> None:
    _auth_headers(content_client)

    response = content_client.get(
        "/api/v1/integrations/telegram/status",
        headers=_internal_headers(),
        params={"telegram_user_id": "100500"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["user_id"]
    assert payload == {
        "linked": True,
        "user_id": payload["user_id"],
        "display_name": "User",
    }


def test_telegram_status_returns_unlinked_without_error(content_client: TestClient) -> None:
    response = content_client.get(
        "/api/v1/integrations/telegram/status",
        headers=_internal_headers(),
        params={"telegram_user_id": "404404"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "linked": False,
        "user_id": None,
        "display_name": None,
    }


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

    fresh_response = content_client.get(
        f"/api/v1/notes/{response.json()['note']['slug']}",
        headers=_auth_headers(content_client),
    )
    assert fresh_response.status_code == 200, fresh_response.text
    fresh_obj = fresh_response.json()["objects"][0]
    assert fresh_obj["source"]["externalId"] == "801627037:28"


def test_telegram_media_group_appends_to_explicit_collection_with_item_sources(
    content_client: TestClient,
) -> None:
    _auth_headers(content_client)

    def ingest_photo(
        message_id: int,
        original_message_id: int,
        caption: str | None,
        *,
        target_collection_id: str | None = None,
    ) -> dict:
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
                "target_collection_id": target_collection_id,
            },
            files=files,
        )
        assert response.status_code == 201, response.text
        return response.json()

    first = ingest_photo(29, 28305, "Caption from first album item")
    second = ingest_photo(30, 28306, None, target_collection_id=first["note"]["id"])

    assert first["note"]["type"] == "composite"
    assert second["status"] == "collection_updated"
    assert second["note"]["type"] == "collection"
    assert second["note"]["objects"][0]["caption"] == "Caption from first album item"
    source_urls = [
        source["origin"]["url"]
        for obj in second["note"]["objects"]
        if (source := obj.get("source")) is not None
    ]
    assert source_urls == ["https://t.me/whackdoor/28306"]


def test_telegram_batch_ingest_creates_single_composite_note_with_shared_text(
    content_client: TestClient,
) -> None:
    _auth_headers(content_client)

    shared_caption = "Caption belongs to the whole Telegram message"
    parts = [
        {
            "telegram_message_id": "51",
            "material_type": "photo",
            "message_date": datetime.now(UTC).isoformat(),
            "caption": shared_caption,
            "filename": "first.jpg",
            "mime_type": "image/jpeg",
            "file_index": 0,
            "source": {
                "provider": "telegram",
                "provider_label": "Telegram",
                "external_id": "801627037:51:0",
                "group_id": "album-51",
                "raw_payload": {"message_id": 51, "media_group_id": "album-51"},
            },
        },
        {
            "telegram_message_id": "52",
            "material_type": "video",
            "message_date": datetime.now(UTC).isoformat(),
            "filename": "second.mp4",
            "mime_type": "video/mp4",
            "file_index": 1,
            "source": {
                "provider": "telegram",
                "provider_label": "Telegram",
                "external_id": "801627037:52:1",
                "group_id": "album-51",
                "raw_payload": {"message_id": 52, "media_group_id": "album-51"},
            },
        },
    ]

    response = content_client.post(
        "/api/v1/integrations/telegram/ingest/batch",
        headers=_internal_headers(),
        data={
            "telegram_user_id": "100500",
            "telegram_chat_id": "801627037",
            "parts": json.dumps(parts),
        },
        files=[
            ("files", ("first.jpg", b"\xff\xd8\xff\xe0telegram-image\xff\xd9", "image/jpeg")),
            ("files", ("second.mp4", b"fake-video", "video/mp4")),
        ],
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["status"] == "saved"
    assert payload["note"]["type"] == "composite"
    objects = payload["note"]["objects"]
    assert [obj["type"] for obj in objects] == ["text", "image", "video"]
    assert objects[0]["content"] == shared_caption
    assert objects[1]["caption"] is None
    assert objects[2]["caption"] is None
    assert objects[0]["source"]["externalId"] == "801627037:51:0"
    assert objects[1]["source"]["externalId"] == "801627037:51:0"
    assert objects[2]["source"]["externalId"] == "801627037:52:1"


def test_telegram_photo_without_caption_does_not_use_filename_as_title(
    content_client: TestClient,
) -> None:
    _auth_headers(content_client)

    response = content_client.post(
        "/api/v1/integrations/telegram/ingest",
        headers=_internal_headers(),
        data={
            "telegram_user_id": "100500",
            "telegram_chat_id": "801627037",
            "telegram_message_id": "41",
            "message_date": datetime.now(UTC).isoformat(),
            "material_type": "photo",
            "filename": "telegram-photo-41.jpg",
            "mime_type": "image/jpeg",
        },
        files={
            "file": (
                "telegram-photo-41.jpg",
                b"\xff\xd8\xff\xe0telegram-image\xff\xd9",
                "image/jpeg",
            )
        },
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["note"]["title"] != "telegram-photo-41.jpg"
    assert payload["note"]["title"] != "telegram-photo-41"
    assert payload["note"]["objects"][0]["type"] == "image"
    assert payload["note"]["objects"][0]["filename"] == "telegram-photo-41.jpg"


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
    assert second["status"] == "saved"
    assert second["note"]["type"] == "simple"
    assert second["note"]["objects"][0]["content"] == "Second forwarded note"


def test_telegram_ingest_appends_to_explicit_target_collection(
    content_client: TestClient,
) -> None:
    _auth_headers(content_client)

    first = _ingest_text(content_client, text="First collection item", message_id=1)
    response = content_client.post(
        "/api/v1/integrations/telegram/ingest",
        headers=_internal_headers(),
        data={
            "telegram_user_id": "100500",
            "telegram_chat_id": "9001",
            "telegram_message_id": "2",
            "message_date": datetime.now(UTC).isoformat(),
            "material_type": "text",
            "text": "Second collection item",
            "target_collection_id": first["note"]["id"],
        },
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["status"] == "collection_updated"
    assert payload["note"]["type"] == "collection"
    assert [obj["content"] for obj in payload["note"]["objects"]] == [
        "First collection item",
        "Second collection item",
    ]
