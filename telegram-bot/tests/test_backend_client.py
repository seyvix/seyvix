from __future__ import annotations

import asyncio

import httpx

from telegram_bot.domain.models import Attachment, InboundMaterial, MaterialType, SourceMetadata
from telegram_bot.infrastructure.backend_client import HttpSeyvixBackend


def test_backend_client_ingest_many_posts_batch_payload() -> None:
    async def scenario() -> None:
        captured: dict[str, object] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["headers"] = dict(request.headers)
            captured["body"] = await request.aread()
            return httpx.Response(
                201,
                json={"status": "saved", "note": {"id": "note-1", "title": "note-1"}},
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            backend = HttpSeyvixBackend(
                client=client,
                base_url="http://backend/api/v1",
                internal_token="token",
            )

            payload = await backend.ingest_many(
                [
                    _material("10", "first.jpg", "image/jpeg", b"image-bytes"),
                    _material("11", "second.mp4", "video/mp4", b"video-bytes"),
                ],
                target_collection_id="collection-1",
            )

        assert payload["status"] == "saved"
        assert captured["path"] == "/api/v1/integrations/telegram/ingest/batch"
        assert captured["headers"]["authorization"] == "Bearer token"
        body = captured["body"]
        assert isinstance(body, bytes)
        assert b"collection-1" in body
        assert b'"telegram_message_id": "10"' in body
        assert b'"telegram_message_id": "11"' in body
        assert b"first.jpg" in body
        assert b"image-bytes" in body
        assert b"second.mp4" in body
        assert b"video-bytes" in body

    asyncio.run(scenario())


def _material(
    message_id: str,
    filename: str,
    mime_type: str,
    data: bytes,
) -> InboundMaterial:
    return InboundMaterial(
        telegram_user_id="100500",
        telegram_chat_id="700",
        telegram_message_id=message_id,
        message_date=1_777_777_777,
        material_type=MaterialType.PHOTO,
        text=None,
        caption="Shared caption" if message_id == "10" else None,
        attachment=Attachment(
            file_id=f"file-{message_id}",
            filename=filename,
            mime_type=mime_type,
            data=data,
        ),
        source=SourceMetadata(
            provider="telegram",
            provider_label="Telegram",
            external_id=f"700:{message_id}",
            group_id="album-1",
        ),
    )
