"""Internal Telegram bot API tests (need TEST_DATABASE_URL)."""

import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.core.config import get_settings
from app.main import app
from app.modules.content.cards import merge_source_metadata
from app.modules.content.schemas import SourceMetadataResponse
from app.modules.telegram_integration.models import TelegramBotState
from app.platform.storage.local import LocalVolumeStorage
from tests.conftest import prepare_database, require_database_url
from tests.test_auth import AUTH_ENV, widget_payload

ADMIN_ID = 100500
INTERNAL = {"Authorization": f"Bearer {AUTH_ENV['TELEGRAM_INTERNAL_TOKEN']}"}
BASE = "/api/v1/integrations/telegram"


@pytest.fixture
def tg_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    for key, value in AUTH_ENV.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    database_url = require_database_url()
    try:
        app.state.session_factory = asyncio.run(prepare_database(database_url))
    except OSError as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")
    app.state.storage = LocalVolumeStorage(tmp_path / "storage")
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


def link(client: TestClient, telegram_id: int = ADMIN_ID) -> None:
    response = client.post(
        "/api/v1/auth/telegram-login",
        json=widget_payload(telegram_id=telegram_id, username=None),
    )
    assert response.status_code == 200, response.text
    client.cookies.clear()


def part(
    message_id: int, *, text: str | None = None, file_index: int | None = None, **extra: object
) -> dict[str, object]:
    value: dict[str, object] = {
        "telegram_message_id": str(message_id),
        "material_type": "photo" if file_index is not None else "text",
        "message_date": datetime.now(UTC).isoformat(),
    }
    if text is not None:
        value["text"] = text
    if file_index is not None:
        value.update(
            file_index=file_index, filename=f"photo-{message_id}.jpg", mime_type="image/jpeg"
        )
    value.update(extra)
    return value


def ingest(
    client: TestClient,
    groups: list[list[dict[str, object]]],
    *,
    telegram_id: int = ADMIN_ID,
    files: list[tuple[str, bytes]] | None = None,
    headers: dict[str, str] | None = None,
) -> object:
    payload = {
        "telegram_user_id": telegram_id,
        "telegram_chat_id": str(telegram_id),
        "groups": [{"parts": group} for group in groups],
    }
    return client.post(
        f"{BASE}/ingest",
        headers=INTERNAL if headers is None else headers,
        data={"payload": json.dumps(payload)},
        files=[("files", (name, data, "image/jpeg")) for name, data in files or []] or None,
    )


PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00"
    b"\x00\x00IEND\xaeB`\x82"
)


def test_internal_token_is_required(tg_client: TestClient) -> None:
    bot_token = {"Authorization": "Bearer 123456:test-bot-token"}
    for headers in ({}, {"Authorization": "Bearer wrong"}, bot_token):
        response = tg_client.get(f"{BASE}/users/{ADMIN_ID}", headers=headers)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_telegram_integration_token"


def test_user_status_reports_access_and_link(tg_client: TestClient) -> None:
    unknown = tg_client.get(f"{BASE}/users/555", headers=INTERNAL).json()
    assert unknown["allowed"] is False and unknown["linked"] is False

    admin = tg_client.get(f"{BASE}/users/{ADMIN_ID}", headers=INTERNAL).json()
    assert admin["allowed"] is True and admin["is_admin"] is True and admin["linked"] is False

    link(tg_client)
    linked = tg_client.get(f"{BASE}/users/{ADMIN_ID}", headers=INTERNAL).json()
    assert linked["linked"] is True and linked["user_id"]


def test_bot_admin_commands_manage_access(tg_client: TestClient) -> None:
    forbidden = tg_client.post(
        f"{BASE}/access", headers=INTERNAL, json={"actor_telegram_id": 555, "telegram_user_id": 7}
    )
    assert forbidden.status_code == 403

    granted = tg_client.post(
        f"{BASE}/access",
        headers=INTERNAL,
        json={"actor_telegram_id": ADMIN_ID, "username": "@Pal", "note": "friend"},
    )
    assert granted.status_code == 201, granted.text
    # Username grants bind to the id the bot sees with that username.
    status = tg_client.get(f"{BASE}/users/77?username=pal", headers=INTERNAL).json()
    assert status["allowed"] is True
    listing = tg_client.get(f"{BASE}/access?actor_telegram_id={ADMIN_ID}", headers=INTERNAL).json()
    assert listing["items"][0]["telegram_user_id"] == 77

    revoked = tg_client.post(
        f"{BASE}/access/revoke",
        headers=INTERNAL,
        json={"actor_telegram_id": ADMIN_ID, "telegram_user_id": 77},
    )
    assert revoked.status_code == 200
    assert tg_client.get(f"{BASE}/users/77", headers=INTERNAL).json()["allowed"] is False
    missing = tg_client.post(
        f"{BASE}/access/revoke",
        headers=INTERNAL,
        json={"actor_telegram_id": ADMIN_ID, "telegram_user_id": 77},
    )
    assert missing.status_code == 404


def test_state_mode_finish_and_reminders(tg_client: TestClient) -> None:
    state = tg_client.get(f"{BASE}/state/{ADMIN_ID}", headers=INTERNAL).json()
    assert state["mode"] == "auto"
    bad = tg_client.put(f"{BASE}/state/{ADMIN_ID}/mode", headers=INTERNAL, json={"mode": "x"})
    assert bad.status_code == 422
    manual = tg_client.put(
        f"{BASE}/state/{ADMIN_ID}/mode", headers=INTERNAL, json={"mode": "manual_collection"}
    ).json()
    assert manual["mode"] == "manual_collection"

    finished = tg_client.post(f"{BASE}/state/{ADMIN_ID}/finish", headers=INTERNAL).json()
    assert finished["finished"] is False and finished["state"]["mode"] == "auto"
    claimed = tg_client.post(f"{BASE}/reminders/claim", headers=INTERNAL, json={"idle_seconds": 60})
    assert claimed.json() == {"telegram_user_ids": []}


def test_ingest_requires_access_and_link(tg_client: TestClient) -> None:
    denied = ingest(tg_client, [[part(1, text="hi")]], telegram_id=555)
    assert denied.status_code == 403
    assert denied.json()["error"]["details"][0]["telegram_user_id"] == 555

    not_linked = ingest(tg_client, [[part(1, text="hi")]])
    assert not_linked.status_code == 404
    assert not_linked.json()["error"]["code"] == "telegram_user_not_linked"


def test_ingest_validates_payload_and_file_indexes(tg_client: TestClient) -> None:
    link(tg_client)
    assert ingest(tg_client, []).status_code == 422
    bad_index = ingest(tg_client, [[part(1, file_index=1)]], files=[("a.png", PNG)])
    assert bad_index.status_code == 422
    assert bad_index.json()["error"]["code"] == "invalid_file_index"


def test_ingest_text_and_album_in_one_request(tg_client: TestClient) -> None:
    link(tg_client)
    response = ingest(
        tg_client,
        [
            [part(1, text="Read later https://example.com/a")],
            [
                part(2, file_index=0, caption="album", source=_source(2, "g1")),
                part(3, file_index=1, source=_source(3, "g1")),
            ],
        ],
        files=[("a.png", PNG), ("b.png", PNG)],
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "saved"
    assert body["note"]["id"]


def test_manual_collection_appends_to_active_collection(tg_client: TestClient) -> None:
    link(tg_client)
    tg_client.put(
        f"{BASE}/state/{ADMIN_ID}/mode", headers=INTERNAL, json={"mode": "manual_collection"}
    )

    first = ingest(tg_client, [[part(1, text="first item")]]).json()
    second = ingest(tg_client, [[part(2, text="second item")]]).json()

    assert first["status"] == "collection_started"
    assert second["status"] == "collection_updated"
    state = tg_client.get(f"{BASE}/state/{ADMIN_ID}", headers=INTERNAL).json()
    assert state["active_collection_id"] == second["note"]["id"]

    async def make_idle() -> None:
        async with app.state.session_factory() as session:
            await session.execute(
                update(TelegramBotState).values(
                    manual_collection_last_item_at=datetime.now(UTC) - timedelta(hours=1)
                )
            )
            await session.commit()

    asyncio.run(make_idle())
    claim = tg_client.post(f"{BASE}/reminders/claim", headers=INTERNAL, json={"idle_seconds": 60})
    assert claim.json() == {"telegram_user_ids": [ADMIN_ID]}
    again = tg_client.post(f"{BASE}/reminders/claim", headers=INTERNAL, json={"idle_seconds": 60})
    assert again.json() == {"telegram_user_ids": []}

    finished = tg_client.post(f"{BASE}/state/{ADMIN_ID}/finish", headers=INTERNAL).json()
    assert finished["finished"] is True
    after = ingest(tg_client, [[part(3, text="standalone")]]).json()
    assert after["status"] == "saved"


def _source(message_id: int, group_id: str) -> dict[str, object]:
    return {
        "provider": "telegram",
        "provider_label": "Telegram",
        "external_id": f"{ADMIN_ID}:{message_id}",
        "group_id": group_id,
    }


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

    merged = merge_source_metadata(first, [first, second])

    assert merged.external_id == "801627037:51"
    assert merged.custom_emoji_ids == ["5280586677532774817"]
    assert merged.metadata["custom_emoji_assets"]["5280586677532774817"]["fallback"] == "⚡️"
    assert "custom_emoji_assets" not in first.metadata
