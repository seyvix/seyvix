from __future__ import annotations

import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.modules.content.models import ContentAsset, ContentObject
from app.modules.snapshots.artifacts import SnapshotArtifactGenerator
from tests.test_content import _auth_headers, content_client


def test_snapshot_settings_defaults_and_user_overrides(content_client: TestClient) -> None:
    headers = _auth_headers(content_client)

    default_response = content_client.get("/api/v1/snapshots/settings", headers=headers)

    assert default_response.status_code == 200
    assert default_response.json() == {
        "effective": {
            "screenshot": True,
            "webpage_html": True,
            "pdf": True,
            "markdown": True,
            "archive_org": False,
        },
        "overrides": {
            "screenshot": None,
            "webpage_html": None,
            "pdf": None,
            "markdown": None,
            "archive_org": None,
        },
    }

    update_response = content_client.patch(
        "/api/v1/snapshots/settings",
        headers=headers,
        json={"screenshot": False, "archive_org": True},
    )

    assert update_response.status_code == 200
    assert update_response.json()["effective"] == {
        "screenshot": False,
        "webpage_html": True,
        "pdf": True,
        "markdown": True,
        "archive_org": True,
    }
    assert update_response.json()["overrides"] == {
        "screenshot": False,
        "webpage_html": None,
        "pdf": None,
        "markdown": None,
        "archive_org": True,
    }

    reload_response = content_client.get("/api/v1/snapshots/settings", headers=headers)
    assert reload_response.status_code == 200
    assert reload_response.json()["overrides"]["screenshot"] is False
    assert reload_response.json()["overrides"]["archive_org"] is True


def test_upload_preserves_display_filename_and_queues_snapshot_jobs(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)

    response = content_client.post(
        "/api/v1/notes/file/upload",
        headers=headers,
        data={"create_object": "true"},
        files={"file": ("résumé final.txt", b"Visible text body", "text/plain")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["source_filename"] == "résumé final.txt"
    assert payload["assets"][0]["filename"] == "résumé final.txt"
    assert payload["assets"][0]["thumbnail_url"] is None

    jobs_response = content_client.get(
        "/api/v1/snapshots/jobs",
        headers=headers,
        params={"content_object_id": payload["id"]},
    )

    assert jobs_response.status_code == 200
    jobs = jobs_response.json()["items"]
    assert {job["job_type"] for job in jobs} == {
        "thumbnail",
        "markdown",
        "screenshot",
        "webpage_html",
        "pdf",
    }
    assert all(job["status"] == "pending" for job in jobs)

    artifacts_response = content_client.get(
        "/api/v1/snapshots/artifacts",
        headers=headers,
        params={"content_object_id": payload["id"]},
    )

    assert artifacts_response.status_code == 200
    assert artifacts_response.json()["items"] == []


def test_snapshot_generator_extracts_docx_markdown_and_falls_back_to_svg_preview(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"
    object_dir = storage_root / "user-1" / "research.object"
    source_dir = object_dir / "original"
    source_dir.mkdir(parents=True)
    docx_path = source_dir / "report.docx"
    with zipfile.ZipFile(docx_path, "w") as archive:
        archive.writestr(
            "word/document.xml",
            (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body><w:p><w:r><w:t>First paragraph</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>Second paragraph</w:t></w:r></w:p></w:body></w:document>"
            ),
        )

    content_object = ContentObject(
        id="object-1",
        owner_user_id="user-1",
        slug="research",
        title="Research",
        kind="simple",
        media_type="document",
        storage_path="user-1/research.object",
    )
    asset = ContentAsset(
        id="asset-1",
        content_object_id="object-1",
        role="original",
        media_type="document",
        filename="report.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes=docx_path.stat().st_size,
        storage_path="user-1/research.object/original/report.docx",
    )

    generator = SnapshotArtifactGenerator(storage_root)

    markdown = generator.generate(content_object=content_object, asset=asset, job_type="markdown")
    thumbnail = generator.generate(content_object=content_object, asset=asset, job_type="thumbnail")

    assert markdown.mime_type == "text/markdown"
    assert "First paragraph" in markdown.path.read_text(encoding="utf-8")
    assert "Second paragraph" in markdown.path.read_text(encoding="utf-8")
    assert thumbnail.mime_type == "image/svg+xml"
