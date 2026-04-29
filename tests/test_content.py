import asyncio
import hashlib
import hmac
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import Base, build_session_factory
from app.main import app
from app.modules.auth.models import User
from app.modules.content.models import ContentCategory, ContentObject, ContentTag
from app.modules.content.service import ContentService
from app.platform.events.models import EventOutbox

TELEGRAM_BOT_TOKEN = "123456:test-bot-token"


async def _prepare_database(database_url: str) -> async_sessionmaker:
    engine: AsyncEngine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()
    return build_session_factory(database_url)


def _test_database_url() -> str:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable database for DB-resetting tests.")
    return database_url


@pytest.fixture
def content_client(tmp_path: Path) -> Iterator[TestClient]:
    os.environ["TELEGRAM_BOT_TOKEN"] = TELEGRAM_BOT_TOKEN
    get_settings.cache_clear()
    database_url = _test_database_url()
    try:
        app.state.session_factory = asyncio.run(_prepare_database(database_url))
    except OSError as exc:
        pytest.skip(f"PostgreSQL is not available for content tests: {exc}")

    app.state.content_storage_root = tmp_path / "content-storage"
    with TestClient(app) as client:
        yield client
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
    response = client.post(
        "/api/v1/auth/telegram-login",
        json=_telegram_payload(telegram_id),
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


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


def test_create_text_note_persists_manifest_and_downloads_archive(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)

    payload = _create_text_note(
        content_client,
        headers,
        title="Manual title",
        text="Research note body",
        folder_path="projects/ai",
        tag_names=["AI", "draft"],
    )

    assert payload["kind"] == "simple"
    assert payload["media_type"] == "text"
    assert payload["title"] == "Manual title"
    assert payload["folder"]["path"] == "projects/ai"
    assert [tag["name"] for tag in payload["tags"]] == ["AI", "draft"]
    assert payload["download_url"] == f"/api/v1/notes/{payload['slug']}/download"

    manifests = list(content_client.app.state.content_storage_root.rglob("manifest.json"))
    assert len(manifests) == 1
    assert manifests[0].read_text(encoding="utf-8").find("Manual title") != -1

    download_response = content_client.get(
        f"/api/v1/notes/{payload['slug']}/download",
        headers=headers,
    )

    assert download_response.status_code == 200
    assert download_response.headers["content-type"] == "application/zip"
    assert len(download_response.content) > 100


def test_create_plain_url_note_creates_link_object_and_content_event(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)

    response = content_client.post(
        "/api/v1/notes",
        headers=headers,
        json={"text": "https://example.com/research?item=1"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["kind"] == "simple"
    assert payload["media_type"] == "link"
    assert payload["title"] == "example.com"
    assert payload["source_filename"] == "https://example.com/research?item=1"
    assert payload["assets"][0]["media_type"] == "link"
    assert payload["assets"][0]["mime_type"] == "text/uri-list"
    assert payload["assets"][0]["text_content"] == "https://example.com/research?item=1"

    async def load_outbox_events() -> list[EventOutbox]:
        async with content_client.app.state.session_factory() as session:
            result = await session.scalars(
                select(EventOutbox).where(EventOutbox.entity_id == payload["id"])
            )
            return list(result)

    events = content_client.portal.call(load_outbox_events)
    assert [event.event_name for event in events] == ["content.object.created"]
    assert events[0].payload["metadata"]["media_type"] == "link"
    assert events[0].payload["asset_ids"] == [payload["assets"][0]["id"]]


def test_concurrent_notes_reuse_folder_and_tags_and_allocate_unique_slugs(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        session_factory = await _prepare_database(_test_database_url())
        async with session_factory() as session:
            user = User(telegram_id="100500", display_name="User")
            session.add(user)
            await session.commit()
            await session.refresh(user)
            owner_user_id = user.id

        async def create_note_once(text: str) -> str:
            async with session_factory() as session:
                service = ContentService(session, tmp_path / "content-storage")
                card = await service.create_note(
                    owner_user_id=owner_user_id,
                    media_type="text",
                    text=text,
                    title="Same title",
                    folder_path="projects/ai",
                    tag_names=["AI"],
                    file_upload_ids=[],
                )
                return card.slug

        slugs = await asyncio.gather(
            create_note_once("First note body"),
            create_note_once("Second note body"),
        )

        async with session_factory() as session:
            categories = list(await session.scalars(select(ContentCategory)))
            tags = list(await session.scalars(select(ContentTag)))
            notes = list(await session.scalars(select(ContentObject)))

        assert sorted(slugs) == ["same-title", "same-title-2"]
        assert sorted(category.path for category in categories) == ["projects", "projects/ai"]
        assert [tag.slug for tag in tags] == ["ai"]
        assert len(notes) == 2

    try:
        asyncio.run(scenario())
    except OSError as exc:
        pytest.skip(f"PostgreSQL is not available for content tests: {exc}")


def test_upload_single_files_with_same_object_id_creates_collection(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    object_id = str(uuid4())

    first_response = content_client.post(
        "/api/v1/notes/file/upload",
        headers=headers,
        data={
            "object_id": object_id,
            "title": "Batch import",
            "folder_path": "imports",
        },
        files={"file": ("alpha.txt", b"Alpha body", "text/plain")},
    )
    second_response = content_client.post(
        "/api/v1/notes/file/upload",
        headers=headers,
        data={
            "object_id": object_id,
            "title": "Batch import",
            "folder_path": "imports",
        },
        files={"file": ("cover.png", b"not a real image", "image/png")},
    )

    assert first_response.status_code == 201
    assert first_response.json()["id"] == object_id
    assert first_response.json()["kind"] == "simple"
    assert second_response.status_code == 201
    payload = second_response.json()
    assert payload["id"] == object_id
    assert payload["kind"] == "collection"
    assert payload["title"] == "Batch import"
    assert payload["folder"]["path"] == "imports"
    assert [item["source_filename"] for item in payload["items"]] == ["alpha.txt", "cover.png"]
    assert [item["media_type"] for item in payload["items"]] == ["text", "image"]


def test_search_expands_collections_to_matching_child_objects(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    object_id = str(uuid4())
    content_client.post(
        "/api/v1/notes/file/upload",
        headers=headers,
        data={"object_id": object_id, "title": "Batch import"},
        files={"file": ("alpha.txt", b"Alpha body", "text/plain")},
    )
    collection_response = content_client.post(
        "/api/v1/notes/file/upload",
        headers=headers,
        data={"object_id": object_id, "title": "Batch import"},
        files={"file": ("beta.txt", b"Beta body", "text/plain")},
    )
    collection_slug = collection_response.json()["slug"]

    response = content_client.get("/api/v1/notes?search=alpha", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["source_filename"] == "alpha.txt"
    assert payload["items"][0]["collection"]["slug"] == collection_slug


def test_favorite_and_custom_order_are_exposed_in_note_list(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    first = _create_text_note(content_client, headers, title="First", text="First body")
    second = _create_text_note(content_client, headers, title="Second", text="Second body")

    favorite_response = content_client.patch(
        f"/api/v1/notes/{first['slug']}/favorite",
        headers=headers,
        json={"is_favorite": True},
    )
    assert favorite_response.status_code == 200
    assert favorite_response.json()["is_favorite"] is True

    reorder_response = content_client.patch(
        "/api/v1/notes/order",
        headers=headers,
        json={
            "items": [
                {"slug": second["slug"], "position": 10},
                {"slug": first["slug"], "position": 20},
            ],
        },
    )
    assert reorder_response.status_code == 204

    list_response = content_client.get("/api/v1/notes?sort=custom", headers=headers)

    assert list_response.status_code == 200
    assert [item["slug"] for item in list_response.json()["items"]] == [
        second["slug"],
        first["slug"],
    ]


def test_upload_file_without_object_id_stays_temporary_until_note_creation(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)

    upload_response = content_client.post(
        "/api/v1/notes/file/upload",
        headers=headers,
        files={"file": ("draft.txt", b"Draft body", "text/plain")},
    )
    assert upload_response.status_code == 201
    upload_payload = upload_response.json()
    assert upload_payload["object"] is None
    assert upload_payload["files"][0]["source_filename"] == "draft.txt"
    assert not list(content_client.app.state.content_storage_root.rglob("manifest.json"))

    create_response = content_client.post(
        "/api/v1/notes",
        headers=headers,
        json={
            "title": "Created from upload",
            "file_upload_ids": [upload_payload["files"][0]["id"]],
            "folder_path": "inbox",
        },
    )
    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["kind"] == "simple"
    assert payload["source_filename"] == "draft.txt"
    assert payload["folder"]["path"] == "inbox"
    assert list(content_client.app.state.content_storage_root.rglob("manifest.json"))


def test_upload_accepts_files_field_alias(content_client: TestClient) -> None:
    headers = _auth_headers(content_client)

    for field_name in ("files", "files[]"):
        upload_response = content_client.post(
            "/api/v1/notes/file/upload",
            headers=headers,
            files={field_name: ("draft.txt", b"Draft body", "text/plain")},
        )

        assert upload_response.status_code == 201
        assert upload_response.json()["files"][0]["source_filename"] == "draft.txt"


def test_upload_file_with_create_object_flag_uses_server_generated_object_id(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)

    first_response = content_client.post(
        "/api/v1/notes/file/upload",
        headers=headers,
        data={"create_object": "true", "title": "Server object"},
        files={"file": ("one.txt", b"One", "text/plain")},
    )
    second_response = content_client.post(
        "/api/v1/notes/file/upload",
        headers=headers,
        data={"create_object": "true", "title": "Another object"},
        files={"file": ("two.txt", b"Two", "text/plain")},
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 201
    assert first_response.json()["kind"] == "simple"
    assert second_response.json()["kind"] == "simple"
    assert first_response.json()["id"] != second_response.json()["id"]
    assert first_response.json()["source_filename"] == "one.txt"
    assert second_response.json()["source_filename"] == "two.txt"


def test_repeated_upload_with_object_id_extends_same_object_as_collection(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    object_id = str(uuid4())

    first_response = content_client.post(
        "/api/v1/notes/file/upload",
        headers=headers,
        data={"object_id": object_id, "title": "Target"},
        files={"file": ("one.txt", b"One", "text/plain")},
    )
    second_response = content_client.post(
        "/api/v1/notes/file/upload",
        headers=headers,
        data={"object_id": object_id, "title": "Target"},
        files={"file": ("two.txt", b"Two", "text/plain")},
    )

    assert first_response.status_code == 201
    assert first_response.json()["id"] == object_id
    assert first_response.json()["kind"] == "simple"
    assert second_response.status_code == 201
    payload = second_response.json()
    assert payload["id"] == object_id
    assert payload["kind"] == "collection"
    assert [item["source_filename"] for item in payload["items"]] == ["one.txt", "two.txt"]


def test_merge_moves_objects_and_collections_into_target_collection(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    first = _create_text_note(content_client, headers, title="First", text="First body")
    second = _create_text_note(content_client, headers, title="Second", text="Second body")

    merge_response = content_client.post(
        "/api/v1/notes/merge",
        headers=headers,
        json={"target_slug": first["slug"], "source_slugs": [second["slug"]], "title": "Merged"},
    )
    assert merge_response.status_code == 200
    collection = merge_response.json()
    assert collection["kind"] == "collection"
    assert collection["slug"] == first["slug"]
    assert [item["source_filename"] for item in collection["items"]] == [
        "content.md",
        "content.md",
    ]

    other_collection = content_client.post(
        "/api/v1/notes/file/upload",
        headers=headers,
        data={
            "object_id": (other_collection_id := str(uuid4())),
            "title": "Other collection",
        },
        files={"file": ("one.txt", b"One", "text/plain")},
    )
    other_collection = content_client.post(
        "/api/v1/notes/file/upload",
        headers=headers,
        data={
            "object_id": other_collection_id,
            "title": "Other collection",
        },
        files={"file": ("two.txt", b"Two", "text/plain")},
    ).json()

    collection_merge_response = content_client.post(
        "/api/v1/notes/merge",
        headers=headers,
        json={"target_slug": collection["slug"], "source_slugs": [other_collection["slug"]]},
    )

    assert collection_merge_response.status_code == 200
    merged_items = collection_merge_response.json()["items"]
    assert [item["source_filename"] for item in merged_items] == [
        "content.md",
        "content.md",
        None,
    ]
    nested_collection = merged_items[2]
    assert nested_collection["title"] == "Other collection"
    assert [item["source_filename"] for item in nested_collection["items"]] == [
        "one.txt",
        "two.txt",
    ]


def test_merge_moves_collection_items_into_target_folder(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    target = _create_text_note(
        content_client,
        headers,
        title="Target",
        text="Target body",
        folder_path="work/target",
    )
    source_collection_id = str(uuid4())
    content_client.post(
        "/api/v1/notes/file/upload",
        headers=headers,
        data={
            "object_id": source_collection_id,
            "title": "Source collection",
            "folder_path": "work/source",
        },
        files={"file": ("one.txt", b"One", "text/plain")},
    )
    source_collection = content_client.post(
        "/api/v1/notes/file/upload",
        headers=headers,
        data={
            "object_id": source_collection_id,
            "title": "Source collection",
            "folder_path": "work/source",
        },
        files={"file": ("two.txt", b"Two", "text/plain")},
    ).json()

    merge_response = content_client.post(
        "/api/v1/notes/merge",
        headers=headers,
        json={"target_slug": target["slug"], "source_slugs": [source_collection["slug"]]},
    )

    assert merge_response.status_code == 200
    payload = merge_response.json()
    assert payload["folder"]["path"] == "work/target"
    moved_collection = next(
        item for item in payload["items"] if item["title"] == "Source collection"
    )
    assert moved_collection["folder"]["path"] == "work/target"
    assert [item["source_filename"] for item in moved_collection["items"]] == ["one.txt", "two.txt"]
    assert [item["folder"]["path"] for item in moved_collection["items"]] == [
        "work/target",
        "work/target",
    ]


def test_folder_tree_and_folder_tags_are_available(content_client: TestClient) -> None:
    headers = _auth_headers(content_client)
    _create_text_note(
        content_client,
        headers,
        title="Folder note",
        text="Folder body",
        folder_path="work/research",
        tag_names=["ml"],
    )
    _create_text_note(
        content_client,
        headers,
        title="Other folder note",
        text="Other body",
        folder_path="work/archive",
    )

    tree_response = content_client.get("/api/v1/folders", headers=headers)
    folder_response = content_client.get("/api/v1/folders/work/research", headers=headers)
    notes_response = content_client.get("/api/v1/notes?folders=work/research", headers=headers)

    assert tree_response.status_code == 200
    assert tree_response.json()["items"][0]["name"] == "work"
    assert {child["path"] for child in tree_response.json()["items"][0]["children"]} == {
        "work/archive",
        "work/research",
    }
    assert folder_response.status_code == 200
    assert folder_response.json()["folder"]["path"] == "work/research"
    assert folder_response.json()["tags"][0]["name"] == "ml"
    assert folder_response.json()["tags"][0]["slug"] == "ml"
    assert notes_response.status_code == 200
    assert len(notes_response.json()["items"]) == 1
    assert notes_response.json()["items"][0]["folder"]["path"] == "work/research"
