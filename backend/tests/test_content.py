import asyncio
import base64
import hashlib
import hmac
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import Base, build_session_factory
from app.main import app
from app.modules.auth.models import User
from app.modules.content.models import ContentObject, ContentTag
from app.modules.content.service import ContentService
from app.modules.snapshots.models import SnapshotArtifact, SnapshotJob
from app.modules.tags.models import TaggingJob
from app.modules.taxonomy.models import (
    TaxonomyCategory,
    TaxonomyClassificationJob,
    TaxonomyContentAssignment,
)
from app.platform.events.models import EventOutbox
from app.platform.storage.service import StorageObjectInfo, StoredObject

TELEGRAM_BOT_TOKEN = "123456:test-bot-token"
PNG_3X2 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAMAAAACCAYAAACddGYaAAAADUlEQVR42mP8z8BQDwAFgwJ/lz6c"
    "WQAAAABJRU5ErkJggg=="
)


class InMemoryRangeStorage:
    bucket = "app-storage"
    storage_backend = "s3"

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str | None]] = {}
        self.get_bytes_calls = 0
        self.iter_ranges: list[tuple[str, int, int | None]] = []
        self.fail_get_bytes = False

    def put_bytes(
        self,
        *,
        storage_key: str,
        data: bytes,
        content_type: str | None,
    ) -> StoredObject:
        self.objects[storage_key] = (data, content_type)
        return StoredObject(
            storage_backend=self.storage_backend,
            bucket=self.bucket,
            storage_key=storage_key,
            storage_ref=f"s3://{self.bucket}/{storage_key}",
            content_type=content_type,
            size_bytes=len(data),
            checksum=f"sha256:{hashlib.sha256(data).hexdigest()}",
        )

    def get_bytes(self, storage_key: str) -> bytes:
        self.get_bytes_calls += 1
        if self.fail_get_bytes:
            raise AssertionError("asset endpoint must not fetch the full object")
        return self.objects[storage_key][0]

    def stat_object(self, storage_key: str) -> StorageObjectInfo:
        data, content_type = self.objects[storage_key]
        return StorageObjectInfo(size_bytes=len(data), content_type=content_type)

    def iter_object_bytes(
        self,
        storage_key: str,
        *,
        offset: int = 0,
        length: int | None = None,
        chunk_size: int = 1024 * 1024,
    ) -> Iterator[bytes]:
        self.iter_ranges.append((storage_key, offset, length))
        data = self.objects[storage_key][0]
        limit = len(data) if length is None else min(offset + length, len(data))
        for index in range(offset, limit, chunk_size):
            yield data[index : min(index + chunk_size, limit)]

    def delete_object(self, storage_key: str) -> None:
        self.objects.pop(storage_key, None)


def test_image_dimensions_from_png_header() -> None:
    assert ContentService._image_dimensions_from_header(PNG_3X2) == (3, 2)


def test_extract_links_from_markdown_url_keeps_clean_target() -> None:
    links, text = ContentService._extract_links_from_text(
        "[https://habr.com/ru/articles/551948/](https://habr.com/ru/articles/551948/)"
    )

    assert links == ["https://habr.com/ru/articles/551948/"]
    assert text == (
        "![favicon](https://favicon.yandex.net/favicon/habr.com) "
        "[https://habr.com/ru/articles/551948/](https://habr.com/ru/articles/551948/)"
    )


async def _prepare_database(database_url: str) -> async_sessionmaker:
    engine: AsyncEngine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
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
    os.environ["STORAGE_BACKEND"] = "local"
    get_settings.cache_clear()
    database_url = _test_database_url()
    try:
        app.state.session_factory = asyncio.run(_prepare_database(database_url))
    except OSError as exc:
        pytest.skip(f"PostgreSQL is not available for content tests: {exc}")

    with TestClient(app) as client:
        app.state.content_storage_root = tmp_path / "content-storage"
        app.state.storage_backend = None
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

    assert payload["type"] == "simple"
    assert payload["objects"][0]["type"] == "text"
    assert payload["objects"][0]["mimeType"] == "text/markdown"
    assert payload["objects"][0]["content"] == "Research note body"
    assert payload["title"] == "Manual title"
    assert "folder" not in payload
    assert payload["taxonomyCategory"]["path"] == "projects/ai"
    assert [tag["name"] for tag in payload["tags"]] == ["AI", "draft"]

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


def test_update_text_note_persists_markdown_content(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    payload = _create_text_note(
        content_client,
        headers,
        title="Manual title",
        text="Original body",
    )

    response = content_client.patch(
        f"/api/v1/notes/{payload['id']}",
        headers=headers,
        json={"title": "Renamed note", "text": "Updated **markdown**"},
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["title"] == "Renamed note"
    assert updated["objects"][0]["content"] == "Updated **markdown**"

    fresh_response = content_client.get(
        f"/api/v1/notes/{payload['id']}",
        headers=headers,
    )
    assert fresh_response.status_code == 200
    fresh_payload = fresh_response.json()
    assert fresh_payload["objects"][0]["content"] == "Updated **markdown**"

    asset_response = content_client.get(
        f"/api/v1/notes/{payload['slug']}/asset/{updated['objects'][0]['id']}",
        headers=headers,
    )
    assert asset_response.status_code == 200
    assert asset_response.text == "# Renamed note\n\nUpdated **markdown**\n"


def test_asset_file_supports_cookie_authenticated_range_requests(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    upload_response = content_client.post(
        "/api/v1/notes/file/upload",
        headers=headers,
        files={"file": ("clip.mp4", b"0123456789", "video/mp4")},
    )
    assert upload_response.status_code == 201
    upload_payload = upload_response.json()
    create_response = content_client.post(
        "/api/v1/notes",
        headers=headers,
        json={
            "title": "Clip",
            "file_upload_ids": [upload_payload["files"][0]["id"]],
        },
    )
    assert create_response.status_code == 201
    payload = create_response.json()
    asset = payload["objects"][0]

    response = content_client.get(
        f"/api/v1/notes/{payload['slug']}/asset/{asset['id']}",
        headers={"Range": "bytes=2-5"},
    )

    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["content-type"] == "video/mp4"


def test_asset_file_streams_nonlocal_range_without_full_download(
    content_client: TestClient,
) -> None:
    fake_storage = InMemoryRangeStorage()
    previous_backend = content_client.app.state.storage_backend
    content_client.app.state.storage_backend = fake_storage
    try:
        headers = _auth_headers(content_client)
        upload_response = content_client.post(
            "/api/v1/notes/file/upload",
            headers=headers,
            files={"file": ("clip.mp4", b"0123456789", "video/mp4")},
        )
        assert upload_response.status_code == 201
        upload_payload = upload_response.json()
        create_response = content_client.post(
            "/api/v1/notes",
            headers=headers,
            json={
                "title": "Clip",
                "file_upload_ids": [upload_payload["files"][0]["id"]],
            },
        )
        assert create_response.status_code == 201
        payload = create_response.json()
        asset = payload["objects"][0]
        get_bytes_calls_before_asset_request = fake_storage.get_bytes_calls
        fake_storage.fail_get_bytes = True

        response = content_client.get(
            f"/api/v1/notes/{payload['slug']}/asset/{asset['id']}",
            headers={"Range": "bytes=2-5"},
        )
    finally:
        content_client.app.state.storage_backend = previous_backend

    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["content-type"] == "video/mp4"
    assert fake_storage.get_bytes_calls == get_bytes_calls_before_asset_request
    assert len(fake_storage.iter_ranges) == 1
    range_storage_key, offset, length = fake_storage.iter_ranges[0]
    assert range_storage_key in fake_storage.objects
    assert (offset, length) == (2, 4)


def test_create_text_note_uses_first_clean_markdown_line_as_title(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)

    response = content_client.post(
        "/api/v1/notes",
        headers=headers,
        json={
            "media_type": "text",
            "text": "{{tg_emoji:5280586677532774817|⚡}} **Важно**\n"
            "Вторая строка остается в тексте",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "⚡ Важно"
    assert payload["objects"][0]["content"].startswith(
        "{{tg_emoji:5280586677532774817|⚡}} **Важно**"
    )


def test_deleted_notes_go_to_trash_and_can_be_restored(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    note = _create_text_note(
        content_client,
        headers,
        title="Trash target",
        text="Trash body",
    )

    delete_response = content_client.request(
        "DELETE",
        "/api/v1/notes",
        headers=headers,
        json={"slugs": [note["slug"]]},
    )
    assert delete_response.status_code == 204

    assert content_client.get(f"/api/v1/notes/{note['slug']}", headers=headers).status_code == 404
    list_response = content_client.get("/api/v1/notes", headers=headers)
    assert note["slug"] not in {item["slug"] for item in list_response.json()["items"]}

    trash_response = content_client.get("/api/v1/notes/trash", headers=headers)
    assert trash_response.status_code == 200, trash_response.text
    assert [item["slug"] for item in trash_response.json()["items"]] == [note["slug"]]

    restore_response = content_client.post(
        f"/api/v1/notes/{note['slug']}/restore",
        headers=headers,
    )
    assert restore_response.status_code == 200, restore_response.text
    assert restore_response.json()["slug"] == note["slug"]
    assert content_client.get(f"/api/v1/notes/{note['slug']}", headers=headers).status_code == 200


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
    assert payload["type"] == "composite"
    assert payload["objects"][0]["type"] == "link"
    assert payload["title"] == "example.com"
    assert "folder" not in payload
    assert payload["taxonomyCategory"] is None
    assert payload["objects"][0]["mimeType"] == "text/uri-list"
    assert payload["objects"][0]["content"] == "https://example.com/research?item=1"

    async def load_processing_rows() -> tuple[
        list[EventOutbox],
        list[SnapshotJob],
        list[TaggingJob],
        list[TaxonomyClassificationJob],
    ]:
        async with content_client.app.state.session_factory() as session:
            events_result = await session.scalars(
                select(EventOutbox).where(EventOutbox.entity_id == payload["id"])
            )
            snapshots_result = await session.scalars(
                select(SnapshotJob).where(SnapshotJob.content_object_id == payload["id"])
            )
            tags_result = await session.scalars(
                select(TaggingJob).where(TaggingJob.content_object_id == payload["id"])
            )
            taxonomy_result = await session.scalars(
                select(TaxonomyClassificationJob).where(
                    TaxonomyClassificationJob.content_object_id == payload["id"]
                )
            )
            return (
                list(events_result),
                list(snapshots_result),
                list(tags_result),
                list(taxonomy_result),
            )

    events, snapshot_jobs, tag_jobs, taxonomy_jobs = content_client.portal.call(
        load_processing_rows
    )
    assert [event.event_name for event in events] == ["content.object.created"]
    assert events[0].payload["metadata"]["media_type"] == "link"
    assert events[0].payload["asset_ids"] == [payload["objects"][0]["id"]]
    assert {job.job_type for job in snapshot_jobs} >= {
        "thumbnail",
        "markdown",
        "pdf",
        "screenshot",
    }
    assert tag_jobs == []
    assert taxonomy_jobs == []


def test_create_plain_url_note_uses_fetched_page_title(
    content_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _auth_headers(content_client)

    async def fake_fetch_title(url: str) -> str | None:
        assert url == "https://example.com/research?item=1"
        return "Research Page Title"

    monkeypatch.setattr(
        ContentService,
        "_fetch_link_page_title",
        staticmethod(fake_fetch_title),
        raising=False,
    )

    response = content_client.post(
        "/api/v1/notes",
        headers=headers,
        json={"text": "https://example.com/research?item=1"},
    )

    assert response.status_code == 201
    assert response.json()["title"] == "Research Page Title"


def test_create_plain_url_note_ignores_url_payload_title_for_page_title(
    content_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _auth_headers(content_client)
    url = "https://example.com/research?item=1"

    async def fake_fetch_title(fetch_url: str) -> str | None:
        assert fetch_url == url
        return "Research Page Title"

    monkeypatch.setattr(
        ContentService,
        "_fetch_link_page_title",
        staticmethod(fake_fetch_title),
        raising=False,
    )

    response = content_client.post(
        "/api/v1/notes",
        headers=headers,
        json={"title": url, "text": url},
    )

    assert response.status_code == 201
    assert response.json()["title"] == "Research Page Title"


def test_create_text_with_link_keeps_text_title_instead_of_page_title(
    content_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _auth_headers(content_client)

    async def fake_fetch_title(url: str) -> str | None:
        return "Research Page Title"

    monkeypatch.setattr(
        ContentService,
        "_fetch_link_page_title",
        staticmethod(fake_fetch_title),
        raising=False,
    )

    response = content_client.post(
        "/api/v1/notes",
        headers=headers,
        json={"text": "Read later https://example.com/research?item=1"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "Read later https://example.com/research?item=1"
    assert {obj["type"] for obj in payload["objects"]} == {"link", "text"}


def test_create_text_with_link_uses_first_clean_markdown_line_for_title(
    content_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _auth_headers(content_client)

    async def fake_fetch_title(url: str) -> str | None:
        return "Research Page Title"

    monkeypatch.setattr(
        ContentService,
        "_fetch_link_page_title",
        staticmethod(fake_fetch_title),
        raising=False,
    )

    response = content_client.post(
        "/api/v1/notes",
        headers=headers,
        json={
            "text": "# {{tg_emoji:5280586677532774817|⚡}} **Read later**\n"
            "Details https://example.com/research?item=1",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "⚡ Read later"
    assert {obj["type"] for obj in payload["objects"]} == {"link", "text"}


def test_markdown_url_equal_to_label_is_saved_as_plain_link_note(
    content_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _auth_headers(content_client)
    url = "https://example.com/research?item=1"

    async def fake_fetch_title(fetch_url: str) -> str | None:
        assert fetch_url == url
        return "Research Page Title"

    monkeypatch.setattr(
        ContentService,
        "_fetch_link_page_title",
        staticmethod(fake_fetch_title),
        raising=False,
    )

    response = content_client.post(
        "/api/v1/notes",
        headers=headers,
        json={"title": url, "text": f"[{url}]({url})"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "Research Page Title"
    assert [(obj["type"], obj["content"]) for obj in payload["objects"]] == [("link", url)]


def _many_links_text(count: int = 5) -> tuple[str, list[str]]:
    urls = [f"https://example.com/research-{index}" for index in range(1, count + 1)]
    return "Read later\n" + "\n".join(urls), urls


def test_text_note_with_many_links_processes_first_three_and_prompts_for_rest(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    text_value, urls = _many_links_text()

    response = content_client.post(
        "/api/v1/notes",
        headers=headers,
        json={"text": text_value},
    )

    assert response.status_code == 201
    payload = response.json()
    link_objects = [obj for obj in payload["objects"] if obj["type"] == "link"]
    text_objects = [obj for obj in payload["objects"] if obj["type"] == "text"]
    assert [obj["content"] for obj in link_objects] == urls[:3]
    assert len(text_objects) == 1
    assert urls[4] in text_objects[0]["content"]
    assert payload["deferredLinkSnapshots"]["totalLinks"] == 5
    assert payload["deferredLinkSnapshots"]["processedLinks"] == 3
    assert payload["deferredLinkSnapshots"]["remainingLinks"] == 2
    assert payload["deferredLinkSnapshots"]["status"] == "pending"

    async def load_snapshot_jobs() -> list[SnapshotJob]:
        async with content_client.app.state.session_factory() as session:
            result = await session.scalars(
                select(SnapshotJob).where(SnapshotJob.content_object_id == payload["id"])
            )
            return list(result)

    snapshot_jobs = content_client.portal.call(load_snapshot_jobs)
    assert {job.source_asset_id for job in snapshot_jobs} == {obj["id"] for obj in link_objects}


def test_accept_deferred_link_snapshots_adds_remaining_links_from_text(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    text_value, urls = _many_links_text()
    created = content_client.post(
        "/api/v1/notes",
        headers=headers,
        json={"text": text_value},
    ).json()

    response = content_client.post(
        f"/api/v1/notes/{created['slug']}/link-snapshots/decision",
        headers=headers,
        json={"decision": "accept"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["deferredLinkSnapshots"] is None
    link_objects = [obj for obj in payload["objects"] if obj["type"] == "link"]
    assert [obj["content"] for obj in link_objects] == urls

    async def load_snapshot_jobs() -> list[SnapshotJob]:
        async with content_client.app.state.session_factory() as session:
            result = await session.scalars(
                select(SnapshotJob).where(SnapshotJob.content_object_id == payload["id"])
            )
            return list(result)

    snapshot_jobs = content_client.portal.call(load_snapshot_jobs)
    assert {job.source_asset_id for job in snapshot_jobs} == {obj["id"] for obj in link_objects}


def test_reject_deferred_link_snapshots_hides_prompt_without_adding_links(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    text_value, urls = _many_links_text()
    created = content_client.post(
        "/api/v1/notes",
        headers=headers,
        json={"text": text_value},
    ).json()

    response = content_client.post(
        f"/api/v1/notes/{created['slug']}/link-snapshots/decision",
        headers=headers,
        json={"decision": "reject"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["deferredLinkSnapshots"] is None
    link_objects = [obj for obj in payload["objects"] if obj["type"] == "link"]
    assert [obj["content"] for obj in link_objects] == urls[:3]


def test_deferred_link_snapshot_prompt_expires_after_twelve_hours(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    text_value, _ = _many_links_text()
    created = content_client.post(
        "/api/v1/notes",
        headers=headers,
        json={"text": text_value},
    ).json()

    async def age_note() -> None:
        async with content_client.app.state.session_factory() as session:
            note = await session.scalar(
                select(ContentObject).where(ContentObject.id == created["id"])
            )
            assert note is not None
            note.created_at = datetime.now(UTC) - timedelta(hours=13)
            await session.commit()

    content_client.portal.call(age_note)

    response = content_client.get(f"/api/v1/notes/{created['slug']}", headers=headers)

    assert response.status_code == 200
    assert response.json()["deferredLinkSnapshots"] is None


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
            categories = list(await session.scalars(select(TaxonomyCategory)))
            tags = list(await session.scalars(select(ContentTag)))
            notes = list(await session.scalars(select(ContentObject)))
            assignments = list(await session.scalars(select(TaxonomyContentAssignment)))

        assert sorted(slugs) == ["same-title", "same-title-2"]
        assert sorted(category.path for category in categories) == [
            "projects",
            "projects/ai",
        ]
        assert [tag.slug for tag in tags] == ["ai"]
        assert len(notes) == 2
        assert all(note.category_id is None for note in notes)
        assert len(assignments) == 2
        assert {assignment.category_path_snapshot for assignment in assignments} == {"projects/ai"}

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
    assert first_response.json()["type"] == "simple"
    assert second_response.status_code == 201
    payload = second_response.json()
    assert payload["id"] == object_id
    assert payload["type"] == "collection"
    assert payload["title"] == "Batch import"
    assert payload["taxonomyCategory"]["path"] == "imports"
    assert [obj["filename"] for obj in payload["objects"]] == ["alpha.txt", "cover.png"]
    assert [obj["type"] for obj in payload["objects"]] == ["text", "image"]


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
    row = payload["items"][0]
    assert row["objects"][0]["filename"] == "alpha.txt"
    assert row["collection"]["slug"] == collection_slug


def test_card_note_list_truncates_large_text_but_detail_stays_full(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    long_text = "Long search payload. " * 200
    note = _create_text_note(
        content_client,
        headers,
        title="Payload note",
        text=long_text,
    )

    list_response = content_client.get("/api/v1/notes?view=card", headers=headers)
    detail_response = content_client.get(
        f"/api/v1/notes/{note['slug']}",
        headers=headers,
    )

    assert list_response.status_code == 200
    list_object = list_response.json()["items"][0]["objects"][0]
    assert list_object["content"].endswith("...")
    assert len(list_object["content"]) < len(long_text)

    assert detail_response.status_code == 200
    assert detail_response.json()["objects"][0]["content"] == long_text


def test_card_note_list_omits_source_raw_payload_from_http_response(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    note = _create_text_note(
        content_client,
        headers,
        title="Heavy source note",
        text="Readable card text. " * 200,
    )

    async def attach_heavy_source() -> None:
        async with content_client.app.state.session_factory() as session:
            content_object = await session.scalar(
                select(ContentObject).where(ContentObject.id == note["id"])
            )
            assert content_object is not None
            await ContentService(session).attach_source_metadata(
                owner_user_id=content_object.owner_user_id,
                content_object_id=content_object.id,
                source={
                    "provider": "telegram",
                    "provider_label": "Telegram",
                    "external_id": "message-1",
                    "raw_payload": {"body": "x" * 200_000},
                    "metadata": {
                        "custom_emoji_assets": {
                            "1": {"data_url": "data:image/png;base64," + "a" * 100_000}
                        }
                    },
                },
            )
            await session.commit()

    content_client.portal.call(attach_heavy_source)

    list_response = content_client.get("/api/v1/notes?view=card", headers=headers)
    detail_response = content_client.get(f"/api/v1/notes/{note['slug']}", headers=headers)

    assert list_response.status_code == 200
    list_payload = list_response.json()
    serialized_list = list_response.content.decode("utf-8")
    assert len(list_response.content) < 20_000
    assert "rawPayload" not in serialized_list
    assert "custom_emoji_assets" not in serialized_list
    assert "source" not in list_payload["items"][0]

    assert detail_response.status_code == 200
    detail_source = detail_response.json()["source"]
    assert detail_source["rawPayload"]["body"].startswith("x")


def test_card_note_list_supports_limit_offset_pagination(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    first = _create_text_note(content_client, headers, title="First", text="First body")
    second = _create_text_note(content_client, headers, title="Second", text="Second body")
    third = _create_text_note(content_client, headers, title="Third", text="Third body")

    reorder_response = content_client.patch(
        "/api/v1/notes/order",
        headers=headers,
        json={
            "items": [
                {"slug": first["slug"], "position": 10},
                {"slug": second["slug"], "position": 20},
                {"slug": third["slug"], "position": 30},
            ],
        },
    )
    assert reorder_response.status_code == 204

    first_page = content_client.get(
        "/api/v1/notes?view=card&sort=custom&limit=2",
        headers=headers,
    )
    second_page = content_client.get(
        "/api/v1/notes?view=card&sort=custom&limit=2&offset=2",
        headers=headers,
    )

    assert first_page.status_code == 200
    assert [item["slug"] for item in first_page.json()["items"]] == [
        first["slug"],
        second["slug"],
    ]
    assert first_page.json()["nextOffset"] == 2

    assert second_page.status_code == 200
    assert [item["slug"] for item in second_page.json()["items"]] == [third["slug"]]
    assert "nextOffset" not in second_page.json()


def test_card_note_list_keeps_video_preview_thumbnail_without_snapshot_views(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    upload_response = content_client.post(
        "/api/v1/notes/file/upload",
        headers=headers,
        data={"create_object": "true", "title": "Preview video"},
        files={"file": ("clip.mp4", b"not a real video", "video/mp4")},
    )
    assert upload_response.status_code == 201
    upload_payload = upload_response.json()
    note = upload_payload.get("object") or upload_payload
    asset_id = note["objects"][0]["id"]

    async def add_thumbnail_artifact() -> None:
        async with content_client.app.state.session_factory() as session:
            content_object = await session.scalar(
                select(ContentObject).where(ContentObject.id == note["id"])
            )
            assert content_object is not None
            session.add(
                SnapshotArtifact(
                    owner_user_id=content_object.owner_user_id,
                    content_object_id=content_object.id,
                    source_asset_id=asset_id,
                    artifact_type="thumbnail",
                    filename="clip-thumbnail.jpg",
                    mime_type="image/jpeg",
                    size_bytes=128,
                    storage_path="snapshots/clip-thumbnail.jpg",
                    status="ready",
                )
            )
            await session.commit()

    content_client.portal.call(add_thumbnail_artifact)

    list_response = content_client.get("/api/v1/notes?view=card", headers=headers)

    assert list_response.status_code == 200
    video_object = list_response.json()["items"][0]["objects"][0]
    assert video_object["type"] == "video"
    assert video_object["thumbnailUrl"] == (
        f"/api/v1/notes/{note['slug']}/asset/{asset_id}/thumbnail"
    )
    assert "snapshotViews" not in video_object


def test_card_note_list_keeps_link_preview_thumbnail_and_text_without_heavy_fields(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    create_response = content_client.post(
        "/api/v1/notes",
        headers=headers,
        json={
            "media_type": "link",
            "title": "Example link",
            "text": "https://example.com/article",
        },
    )
    assert create_response.status_code == 201
    note = create_response.json()
    asset_id = note["objects"][0]["id"]
    thumbnail_text_path = (
        content_client.app.state.content_storage_root / "snapshots" / "link-preview.txt"
    )
    thumbnail_text_path.parent.mkdir(parents=True, exist_ok=True)
    thumbnail_text_path.write_text("Readable website preview", encoding="utf-8")

    async def add_link_artifacts() -> None:
        async with content_client.app.state.session_factory() as session:
            content_object = await session.scalar(
                select(ContentObject).where(ContentObject.id == note["id"])
            )
            assert content_object is not None
            for artifact_type, filename, mime_type, storage_path in [
                (
                    "thumbnail",
                    "link-thumbnail.jpg",
                    "image/jpeg",
                    "snapshots/link-thumbnail.jpg",
                ),
                (
                    "thumbnail_text",
                    "link-preview.txt",
                    "text/plain",
                    "snapshots/link-preview.txt",
                ),
            ]:
                session.add(
                    SnapshotArtifact(
                        owner_user_id=content_object.owner_user_id,
                        content_object_id=content_object.id,
                        source_asset_id=asset_id,
                        artifact_type=artifact_type,
                        filename=filename,
                        mime_type=mime_type,
                        size_bytes=64,
                        storage_path=storage_path,
                        status="ready",
                    )
                )
            await session.commit()

    content_client.portal.call(add_link_artifacts)

    list_response = content_client.get("/api/v1/notes?view=card", headers=headers)

    assert list_response.status_code == 200
    link_object = list_response.json()["items"][0]["objects"][0]
    assert link_object["type"] == "link"
    assert link_object["thumbnailUrl"] == (
        f"/api/v1/notes/{note['slug']}/asset/{asset_id}/thumbnail"
    )
    assert link_object["thumbnailText"] == "Readable website preview"
    assert "source" not in link_object
    assert "snapshotViews" not in link_object


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
    assert favorite_response.json()["isFavorite"] is True

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


def test_custom_order_defaults_new_notes_to_top(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    first = _create_text_note(content_client, headers, title="First", text="First body")
    second = _create_text_note(content_client, headers, title="Second", text="Second body")

    list_response = content_client.get("/api/v1/notes?sort=custom", headers=headers)

    assert list_response.status_code == 200
    assert [item["slug"] for item in list_response.json()["items"]][:2] == [
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
    assert payload["type"] == "simple"
    assert payload["objects"][0]["filename"] == "draft.txt"
    assert payload["taxonomyCategory"]["path"] == "inbox"
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
    assert first_response.json()["type"] == "simple"
    assert second_response.json()["type"] == "simple"
    assert first_response.json()["id"] != second_response.json()["id"]
    assert first_response.json()["objects"][0]["filename"] == "one.txt"
    assert second_response.json()["objects"][0]["filename"] == "two.txt"


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
    assert first_response.json()["type"] == "simple"
    assert second_response.status_code == 201
    payload = second_response.json()
    assert payload["id"] == object_id
    assert payload["type"] == "collection"
    assert [obj["filename"] for obj in payload["objects"]] == ["one.txt", "two.txt"]


def test_image_upload_returns_dimensions_for_card_layout(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)

    response = content_client.post(
        "/api/v1/notes/file/upload",
        headers=headers,
        data={"create_object": "true", "title": "Tiny image"},
        files={"file": ("tiny.png", PNG_3X2, "image/png")},
    )

    assert response.status_code == 201
    image_object = response.json()["objects"][0]
    assert image_object["type"] == "image"
    assert image_object["imageWidth"] == 3
    assert image_object["imageHeight"] == 2
    assert image_object["visualWidth"] == 3
    assert image_object["visualHeight"] == 2

    list_response = content_client.get("/api/v1/notes", headers=headers)

    assert list_response.status_code == 200
    listed_object = list_response.json()["items"][0]["objects"][0]
    assert listed_object["imageWidth"] == 3
    assert listed_object["imageHeight"] == 2
    assert listed_object["visualWidth"] == 3
    assert listed_object["visualHeight"] == 2


def test_collection_omits_soft_deleted_children_from_objects(
    content_client: TestClient,
) -> None:
    """A child sub-note that the user deleted should not appear in the
    collection's `objects` list, even though the collection_items link
    still exists for restore-from-trash purposes."""
    headers = _auth_headers(content_client)
    object_id = str(uuid4())

    content_client.post(
        "/api/v1/notes/file/upload",
        headers=headers,
        data={"object_id": object_id, "title": "Templates"},
        files={"file": ("one.txt", b"One", "text/plain")},
    )
    second = content_client.post(
        "/api/v1/notes/file/upload",
        headers=headers,
        data={"object_id": object_id, "title": "Templates"},
        files={"file": ("two.txt", b"Two", "text/plain")},
    )
    assert second.status_code == 201
    payload = second.json()
    collection_slug = payload["slug"]
    children = payload["objects"]
    assert len(children) == 2
    victim_slug = children[0]["slug"]
    survivor_slug = children[1]["slug"]
    assert victim_slug and survivor_slug

    delete_response = content_client.request(
        "DELETE",
        "/api/v1/notes",
        headers=headers,
        json={"slugs": [victim_slug]},
    )
    assert delete_response.status_code == 204, delete_response.text

    detail = content_client.get(
        f"/api/v1/notes/{collection_slug}",
        headers=headers,
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    remaining_slugs = [obj.get("slug") for obj in body["objects"]]
    assert victim_slug not in remaining_slugs, body
    assert survivor_slug in remaining_slugs, body


def test_merge_moves_objects_and_collections_into_target_collection(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    first = _create_text_note(content_client, headers, title="First", text="First body")
    second = _create_text_note(content_client, headers, title="Second", text="Second body")

    merge_response = content_client.post(
        "/api/v1/notes/merge",
        headers=headers,
        json={
            "target_slug": first["slug"],
            "source_slugs": [second["slug"]],
            "title": "Merged",
        },
    )
    assert merge_response.status_code == 200
    collection = merge_response.json()
    assert collection["type"] == "collection"
    assert collection["slug"] == first["slug"]
    assert [obj["filename"] for obj in collection["objects"]] == [
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
        json={
            "target_slug": collection["slug"],
            "source_slugs": [other_collection["slug"]],
        },
    )

    assert collection_merge_response.status_code == 200
    merged = collection_merge_response.json()
    objs = merged["objects"]
    assert len(objs) == 3
    assert objs[0]["filename"] == "content.md"
    assert objs[1]["filename"] == "content.md"
    assert any(o.get("slug") == other_collection["slug"] for o in objs)
    nested_payload = content_client.get(
        f"/api/v1/notes/{other_collection['slug']}",
        headers=headers,
    ).json()
    assert nested_payload["title"] == "Other collection"
    assert [obj["filename"] for obj in nested_payload["objects"]] == [
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
        json={
            "target_slug": target["slug"],
            "source_slugs": [source_collection["slug"]],
        },
    )

    assert merge_response.status_code == 200
    payload = merge_response.json()
    assert payload["taxonomyCategory"]["path"] == "work/target"
    moved_payload = content_client.get(
        f"/api/v1/notes/{source_collection['slug']}",
        headers=headers,
    ).json()
    assert moved_payload["taxonomyCategory"]["path"] == "work/target"
    assert [obj["filename"] for obj in moved_payload["objects"]] == [
        "one.txt",
        "two.txt",
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
        title="Nested folder note",
        text="Nested body",
        folder_path="work/research/llm",
        tag_names=["ml", "rag"],
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
    assert tree_response.json()["items"][0]["direct_count"] == 0
    assert tree_response.json()["items"][0]["total_count"] == 3
    assert {child["path"] for child in tree_response.json()["items"][0]["children"]} == {
        "work/archive",
        "work/research",
    }
    research_node = next(
        child
        for child in tree_response.json()["items"][0]["children"]
        if child["path"] == "work/research"
    )
    assert research_node["direct_count"] == 1
    assert research_node["total_count"] == 2
    assert folder_response.status_code == 200
    assert folder_response.json()["folder"]["path"] == "work/research"
    assert [(tag["slug"], tag["count"]) for tag in folder_response.json()["tags"]] == [
        ("ml", 2),
        ("rag", 1),
    ]
    assert [item["title"] for item in folder_response.json()["notes"]] == [
        "Folder note",
        "Nested folder note",
    ]
    assert folder_response.json()["notes"][0]["taxonomyCategory"]["path"] == "work/research"
    assert folder_response.json()["notes"][1]["taxonomyCategory"]["path"] == "work/research/llm"
    assert notes_response.status_code == 200
    assert len(notes_response.json()["items"]) == 2
    assert notes_response.json()["items"][0]["taxonomyCategory"]["path"] == "work/research"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("**Hello world**", "Hello world"),
        ("__Bold__", "Bold"),
        ("plain title", "plain title"),
        ("# Heading", "Heading"),
        ("### Subheading", "Subheading"),
        ("> quoted line", "quoted line"),
        ("`code`", "code"),
        ("```code```", "code"),
        ("~~strike~~", "strike"),
        ("_italic_", "italic"),
        ("*italic*", "italic"),
        ("**bold** and _italic_ and ~~strike~~", "bold and italic and strike"),
        ("Read [docs](https://example.com) now", "Read docs now"),
        ("<u>underlined</u>", "underlined"),
        ("multi   spaces   collapsed", "multi spaces collapsed"),
        ("snake_case_var stays", "snake_case_var stays"),
        ("2 * 3 = 6", "2 * 3 = 6"),
        ("first line\nsecond line", "first line second line"),
        ("   **trim me**   ", "trim me"),
    ],
)
def test_strip_title_markdown_removes_common_markers(raw: str, expected: str) -> None:
    from app.modules.content.service import _strip_title_markdown

    assert _strip_title_markdown(raw) == expected
