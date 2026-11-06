from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from telegram_bot.domain.enums import BotMode
from telegram_bot.domain.models import Attachment, InboundMaterial, MaterialType
from telegram_bot.infrastructure import backend_client
from telegram_bot.infrastructure.backend_client import (
    BackendError,
    BackendUnavailableError,
    HttpSeyvixBackend,
    IngestItem,
    UploadFile,
)


def _backend(handler: object) -> tuple[httpx.AsyncClient, HttpSeyvixBackend]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    backend = HttpSeyvixBackend(client=client, base_url="http://api/api/v1/", internal_token="t")
    return client, backend


def _material(message_id: str, filename: str | None = None) -> InboundMaterial:
    return InboundMaterial(
        telegram_user_id="42",
        telegram_chat_id="42",
        telegram_message_id=message_id,
        message_date=1_700_000_000,
        material_type=MaterialType.PHOTO if filename else MaterialType.TEXT,
        text=None if filename else "hello",
        caption=None,
        attachment=Attachment(file_id=f"f{message_id}", filename=filename, mime_type="image/jpeg")
        if filename
        else None,
    )


def test_ingest_sends_one_multipart_request_with_streamed_files(tmp_path: Path) -> None:
    photo = tmp_path / "0"
    photo.write_bytes(b"jpeg-bytes")
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["auth"] = request.headers["authorization"]
        captured["body"] = await request.aread()
        return httpx.Response(201, json={"status": "saved", "note": {"id": "n1", "title": "T"}})

    async def scenario() -> None:
        client, backend = _backend(handler)
        async with client:
            saved = await backend.ingest(
                telegram_user_id=42,
                telegram_chat_id="42",
                groups=[
                    [IngestItem(_material("1"), None)],
                    [IngestItem(_material("2", "a.jpg"), 0)],
                ],
                files=[UploadFile(path=photo, filename="a.jpg", mime_type="image/jpeg")],
            )
        assert saved.id == "n1" and saved.status == "saved"

    asyncio.run(scenario())
    assert captured["path"] == "/api/v1/integrations/telegram/ingest"
    assert captured["auth"] == "Bearer t"
    body = captured["body"]
    assert isinstance(body, bytes)
    assert b"jpeg-bytes" in body
    payload_start = body.index(b'{"telegram_user_id"')
    payload = json.loads(body[payload_start : body.index(b"\r\n", payload_start)])
    assert payload["telegram_user_id"] == 42
    assert [len(group["parts"]) for group in payload["groups"]] == [1, 1]
    assert payload["groups"][1]["parts"][0]["file_index"] == 0


def test_connect_errors_are_retried_then_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backend_client, "RETRY_BASE_DELAY_SECONDS", 0)
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("refused", request=request)

    async def scenario() -> None:
        client, backend = _backend(handler)
        async with client:
            with pytest.raises(BackendUnavailableError):
                await backend.get_state(42)

    asyncio.run(scenario())
    assert calls == backend_client.RETRY_ATTEMPTS


def test_read_timeouts_are_not_retried() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("slow", request=request)

    async def scenario() -> None:
        client, backend = _backend(handler)
        async with client:
            with pytest.raises(BackendUnavailableError):
                await backend.set_mode(42, BotMode.SEPARATE)

    asyncio.run(scenario())
    assert calls == 1


def test_error_responses_expose_backend_error_code() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"error": {"code": "access_denied", "message": "no", "details": []}},
        )

    async def scenario() -> None:
        client, backend = _backend(handler)
        async with client:
            with pytest.raises(BackendError) as info:
                await backend.user_status(telegram_user_id=1, username=None)
        assert info.value.code == "access_denied"
        assert info.value.status_code == 403

    asyncio.run(scenario())


def test_user_status_and_state_parsing() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/users/7"):
            assert request.url.params["username"] == "bob"
            return httpx.Response(
                200,
                json={"telegram_user_id": 7, "allowed": True, "is_admin": False, "linked": True},
            )
        return httpx.Response(
            200,
            json={
                "finished": True,
                "state": {
                    "telegram_user_id": 7,
                    "mode": "auto",
                    "active_collection_id": None,
                    "manual_collection_started_at": None,
                },
            },
        )

    async def scenario() -> None:
        client, backend = _backend(handler)
        async with client:
            user = await backend.user_status(telegram_user_id=7, username="bob")
            finished, state = await backend.finish_collection(7)
        assert user.allowed and user.linked and not user.is_admin
        assert finished and state.mode == BotMode.AUTO

    asyncio.run(scenario())
