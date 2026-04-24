import asyncio
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.database import Base, build_session_factory
from app.main import app


async def _prepare_database(database_url: str) -> async_sessionmaker:
    engine: AsyncEngine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()
    return build_session_factory(database_url)


def _test_database_url() -> str:
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    database = os.getenv("POSTGRES_DB", "vkr_api")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"


@pytest.fixture
def content_client(tmp_path: Path) -> Iterator[TestClient]:
    database_url = _test_database_url()
    try:
        app.state.session_factory = asyncio.run(_prepare_database(database_url))
    except OSError as exc:
        pytest.skip(f"PostgreSQL is not available for content tests: {exc}")

    app.state.content_storage_root = tmp_path / "content-storage"
    with TestClient(app) as client:
        yield client


def _auth_headers(client: TestClient, email: str = "user@example.com") -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "display_name": "User",
            "password": "StrongPass123!",
        },
    )
    assert response.status_code == 201
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
        "/api/v1/notes/text",
        headers=headers,
        json={
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


def test_upload_multiple_files_creates_collection_with_child_objects(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)

    response = content_client.post(
        "/api/v1/notes/upload",
        headers=headers,
        data={"title": "Batch import", "folder_path": "imports"},
        files=[
            ("files", ("alpha.txt", b"Alpha body", "text/plain")),
            ("files", ("cover.png", b"not a real image", "image/png")),
        ],
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["kind"] == "collection"
    assert payload["title"] == "Batch import"
    assert payload["folder"]["path"] == "imports"
    assert [item["source_filename"] for item in payload["items"]] == ["alpha.txt", "cover.png"]
    assert [item["media_type"] for item in payload["items"]] == ["text", "image"]


def test_search_expands_collections_to_matching_child_objects(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    collection_response = content_client.post(
        "/api/v1/notes/upload",
        headers=headers,
        data={"title": "Batch import"},
        files=[
            ("files", ("alpha.txt", b"Alpha body", "text/plain")),
            ("files", ("beta.txt", b"Beta body", "text/plain")),
        ],
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


def test_merge_objects_into_collection_and_reject_collection_to_collection_merge(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    first = _create_text_note(content_client, headers, title="First", text="First body")
    second = _create_text_note(content_client, headers, title="Second", text="Second body")
    third = _create_text_note(content_client, headers, title="Third", text="Third body")

    merge_response = content_client.post(
        "/api/v1/notes/collections/merge",
        headers=headers,
        json={"source_slugs": [first["slug"], second["slug"]], "title": "Merged"},
    )
    assert merge_response.status_code == 201
    collection = merge_response.json()
    assert collection["kind"] == "collection"
    assert [item["slug"] for item in collection["items"]] == [first["slug"], second["slug"]]

    transfer_response = content_client.post(
        "/api/v1/notes/collections/merge",
        headers=headers,
        json={"source_slugs": [collection["slug"], third["slug"]]},
    )
    assert transfer_response.status_code == 200
    assert [item["slug"] for item in transfer_response.json()["items"]] == [
        first["slug"],
        second["slug"],
        third["slug"],
    ]

    other_collection = content_client.post(
        "/api/v1/notes/upload",
        headers=headers,
        data={"title": "Other collection"},
        files=[
            ("files", ("one.txt", b"One", "text/plain")),
            ("files", ("two.txt", b"Two", "text/plain")),
        ],
    ).json()

    conflict_response = content_client.post(
        "/api/v1/notes/collections/merge",
        headers=headers,
        json={"source_slugs": [collection["slug"], other_collection["slug"]]},
    )

    assert conflict_response.status_code == 409
    assert conflict_response.json()["error"]["code"] == "collection_merge_conflict"


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
