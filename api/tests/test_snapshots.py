from __future__ import annotations

import struct
import zipfile
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.modules.content.models import ContentAsset, ContentObject
from app.modules.content.schemas import NoteAssetResponse
from app.modules.snapshots.artifacts import (
    FetchedWebpage,
    SnapshotArtifactGenerator,
    UnsupportedSnapshotError,
)
from app.modules.snapshots.browser import BrowserSnapshot
from app.modules.snapshots.service import EffectiveSnapshotSettings, plan_snapshot_job_types
from app.platform.events.models import EventOutbox
from tests.test_content import _auth_headers


def _minimal_jpeg_bytes(work_dir: Path) -> bytes:
    """Valid JPEG bytes so PyMuPDF can open the browser screenshot stub."""
    import fitz

    work_dir.mkdir(parents=True, exist_ok=True)
    dest = work_dir / "_stub_thumb.jpg"
    doc = fitz.open()
    try:
        page = doc.new_page(width=64, height=64)
        pix = page.get_pixmap(alpha=False)
        pix.save(str(dest))
    finally:
        doc.close()
    data = dest.read_bytes()
    dest.unlink(missing_ok=True)
    return data


def _png_bytes(width: int, height: int, color: tuple[int, int, int]) -> bytes:
    scanline = b"\x00" + bytes(color) * width
    image_data = zlib.compress(scanline * height)

    def chunk(kind: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", image_data)
        + chunk(b"IEND", b"")
    )


def test_snapshot_settings_defaults_and_user_overrides(content_client: TestClient) -> None:
    headers = _auth_headers(content_client)

    default_response = content_client.get("/api/v1/snapshots/settings", headers=headers)

    assert default_response.status_code == 200
    assert default_response.json() == {
        "effective": {
            "screenshot": True,
            "webpage_html": False,
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
        "webpage_html": False,
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


def test_upload_preserves_display_filename_and_writes_content_event(
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
    assert payload["objects"][0]["filename"] == "résumé final.txt"
    assert payload["objects"][0]["thumbnailUrl"] is None

    async def load_outbox_events() -> list[EventOutbox]:
        async with content_client.app.state.session_factory() as session:
            result = await session.scalars(
                select(EventOutbox).where(EventOutbox.entity_id == payload["id"])
            )
            return list(result)

    events = content_client.portal.call(load_outbox_events)
    assert [event.event_name for event in events] == ["content.object.created"]
    assert events[0].payload["content_object_id"] == payload["id"]
    assert events[0].payload["asset_ids"] == [payload["objects"][0]["id"]]

    artifacts_response = content_client.get(
        "/api/v1/snapshots/artifacts",
        headers=headers,
        params={"content_object_id": payload["id"]},
    )

    assert artifacts_response.status_code == 200
    assert artifacts_response.json()["items"] == []


def test_snapshot_generator_creates_bounded_jpeg_thumbnail_for_image(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    object_dir = storage_root / "user-1" / "photo.object"
    source_dir = object_dir / "original"
    source_dir.mkdir(parents=True)
    source_path = source_dir / "photo.png"
    source_path.write_bytes(_png_bytes(1200, 900, (210, 48, 48)))

    content_object = ContentObject(
        id="object-1",
        owner_user_id="user-1",
        slug="photo",
        title="Photo",
        kind="simple",
        media_type="image",
        storage_path="user-1/photo.object",
    )
    asset = ContentAsset(
        id="asset-1",
        content_object_id="object-1",
        role="original",
        media_type="image",
        filename="photo.png",
        mime_type="image/png",
        size_bytes=source_path.stat().st_size,
        storage_path="user-1/photo.object/original/photo.png",
    )

    thumbnail = SnapshotArtifactGenerator(storage_root).generate(
        content_object=content_object,
        asset=asset,
        job_type="thumbnail",
    )

    assert thumbnail.filename == "thumbnail.jpg"
    assert thumbnail.mime_type == "image/jpeg"
    assert thumbnail.path.read_bytes().startswith(b"\xff\xd8\xff")

    import fitz

    pixmap = fitz.Pixmap(str(thumbnail.path))
    assert pixmap.width == 512
    assert pixmap.height == 384
    assert thumbnail.size_bytes < source_path.stat().st_size


def test_snapshot_generator_creates_jpeg_thumbnail_for_csv_preview(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    object_dir = storage_root / "user-1" / "table.object"
    source_dir = object_dir / "original"
    source_dir.mkdir(parents=True)
    source_path = source_dir / "table.csv"
    source_path.write_text("name,value\nAlpha,10\nBeta,20\n", encoding="utf-8")

    content_object = ContentObject(
        id="object-1",
        owner_user_id="user-1",
        slug="table",
        title="Table",
        kind="simple",
        media_type="document",
        storage_path="user-1/table.object",
    )
    asset = ContentAsset(
        id="asset-1",
        content_object_id="object-1",
        role="original",
        media_type="document",
        filename="table.csv",
        mime_type="text/csv",
        size_bytes=source_path.stat().st_size,
        storage_path="user-1/table.object/original/table.csv",
    )

    thumbnail = SnapshotArtifactGenerator(storage_root).generate(
        content_object=content_object,
        asset=asset,
        job_type="thumbnail",
    )

    assert thumbnail.filename == "thumbnail.jpg"
    assert thumbnail.mime_type == "image/jpeg"
    assert thumbnail.path.read_bytes().startswith(b"\xff\xd8\xff")

    import fitz

    pixmap = fitz.Pixmap(str(thumbnail.path))
    assert pixmap.width <= 512
    assert pixmap.height <= 512
    assert pixmap.width < pixmap.height


def test_snapshot_job_plan_uses_text_thumbnail_and_skips_existing_markdown() -> None:
    asset = ContentAsset(
        id="asset-1",
        content_object_id="object-1",
        role="original",
        media_type="text",
        filename="note.md",
        mime_type="text/markdown",
        size_bytes=120,
        storage_path="content-assets/object-1/asset-1/original.md",
    )
    settings = EffectiveSnapshotSettings(
        screenshot=True,
        webpage_html=True,
        pdf=True,
        markdown=True,
        archive_org=True,
    )

    assert plan_snapshot_job_types(asset, settings) == ("thumbnail_text", "pdf")


def test_snapshot_job_plan_skips_html_archive_and_pdf_for_existing_pdf() -> None:
    asset = ContentAsset(
        id="asset-1",
        content_object_id="object-1",
        role="original",
        media_type="document",
        filename="report.pdf",
        mime_type="application/pdf",
        size_bytes=120,
        storage_path="content-assets/object-1/asset-1/original.pdf",
    )
    settings = EffectiveSnapshotSettings(
        screenshot=True,
        webpage_html=True,
        pdf=True,
        markdown=True,
        archive_org=True,
    )

    assert plan_snapshot_job_types(asset, settings) == ("thumbnail", "markdown")


def test_snapshot_job_plan_includes_site_jobs_for_link_when_enabled() -> None:
    asset = ContentAsset(
        id="asset-1",
        content_object_id="object-1",
        role="original",
        media_type="link",
        filename="link.url",
        mime_type="text/uri-list",
        size_bytes=120,
        storage_path="content-assets/object-1/asset-1/original.url",
        text_content="https://example.com/research",
    )
    settings = EffectiveSnapshotSettings(
        screenshot=True,
        webpage_html=True,
        pdf=True,
        markdown=True,
        archive_org=True,
    )

    assert plan_snapshot_job_types(asset, settings) == (
        "thumbnail",
        "markdown",
        "pdf",
        "screenshot",
        "webpage_html",
    )


def test_snapshot_job_plan_respects_disabled_markdown_and_pdf_settings() -> None:
    asset = ContentAsset(
        id="asset-1",
        content_object_id="object-1",
        role="original",
        media_type="document",
        filename="slides.pptx",
        mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        size_bytes=120,
        storage_path="content-assets/object-1/asset-1/original.pptx",
    )
    settings = EffectiveSnapshotSettings(
        screenshot=True,
        webpage_html=True,
        pdf=False,
        markdown=False,
        archive_org=True,
    )

    assert plan_snapshot_job_types(asset, settings) == ("thumbnail",)


def test_note_asset_response_exposes_snapshot_representation_fields() -> None:
    response = NoteAssetResponse(
        id="asset-1",
        role="original",
        media_type="document",
        filename="report.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes=120,
        url="/api/v1/notes/note/asset/asset-1",
        thumbnail_url="/api/v1/notes/note/asset/asset-1/thumbnail",
        thumbnail_text="Preview text",
        markdown_url="/api/v1/snapshots/artifacts/markdown-1",
        pdf_url="/api/v1/snapshots/artifacts/pdf-1",
        html_url=None,
    )

    assert response.model_dump() == {
        "id": "asset-1",
        "role": "original",
        "media_type": "document",
        "filename": "report.docx",
        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "size_bytes": 120,
        "url": "/api/v1/notes/note/asset/asset-1",
        "text_content": None,
        "thumbnail_url": "/api/v1/notes/note/asset/asset-1/thumbnail",
        "thumbnail_text": "Preview text",
        "markdown_url": "/api/v1/snapshots/artifacts/markdown-1",
        "pdf_url": "/api/v1/snapshots/artifacts/pdf-1",
        "html_url": None,
        "snapshot_views": [],
        "image_width": None,
        "image_height": None,
    }


def test_snapshot_generator_creates_webpage_artifacts_from_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "storage"
    object_dir = storage_root / "user-1" / "site.object"
    source_dir = object_dir / "original"
    source_dir.mkdir(parents=True)
    source_path = source_dir / "link.url"
    source_path.write_text("https://example.com/research", encoding="utf-8")

    content_object = ContentObject(
        id="object-1",
        owner_user_id="user-1",
        slug="site",
        title="example.com",
        kind="simple",
        media_type="link",
        storage_path="user-1/site.object",
    )
    asset = ContentAsset(
        id="asset-1",
        content_object_id="object-1",
        role="original",
        media_type="link",
        filename="link.url",
        mime_type="text/uri-list",
        size_bytes=source_path.stat().st_size,
        storage_path="user-1/site.object/original/link.url",
        text_content="https://example.com/research",
    )

    stub_html = (
        "<html><head><title>Research</title></head><body><h1>Hello</h1></body></html>"
    )

    def fake_fetch(self: SnapshotArtifactGenerator, url: str) -> FetchedWebpage:
        assert url == "https://example.com/research"
        return FetchedWebpage(url=url, html=stub_html)

    def fake_render_url(url: str) -> BrowserSnapshot:
        assert url == "https://example.com/research"
        return BrowserSnapshot(
            html=stub_html,
            screenshot_bytes=_minimal_jpeg_bytes(tmp_path / "jpeg-stub"),
        )

    def fake_render_url_pdf(url: str) -> bytes:
        assert url == "https://example.com/research"
        return b"%PDF-1.4\n1 0 obj<<>>endobj trailer<<>>\n%%EOF\n"

    monkeypatch.setattr(SnapshotArtifactGenerator, "_fetch_webpage", fake_fetch)
    monkeypatch.setattr("app.modules.snapshots.browser.render_url", fake_render_url)
    monkeypatch.setattr("app.modules.snapshots.browser.render_url_pdf", fake_render_url_pdf)
    generator = SnapshotArtifactGenerator(storage_root)

    html = generator.generate(
        content_object=content_object,
        asset=asset,
        job_type="webpage_html",
    )
    markdown = generator.generate(
        content_object=content_object,
        asset=asset,
        job_type="markdown",
    )
    pdf = generator.generate(content_object=content_object, asset=asset, job_type="pdf")
    thumbnail = generator.generate(
        content_object=content_object,
        asset=asset,
        job_type="thumbnail",
    )

    assert html.mime_type == "text/html"
    html_text = html.path.read_text(encoding="utf-8")
    assert "Hello" in html_text
    assert "h1" in html_text.lower()
    assert markdown.mime_type == "text/markdown"
    assert "Hello" in markdown.path.read_text(encoding="utf-8")
    assert pdf.mime_type == "application/pdf"
    assert pdf.path.read_bytes().startswith(b"%PDF")
    assert thumbnail.mime_type == "image/jpeg"
    assert thumbnail.path.read_bytes().startswith(b"\xff\xd8\xff")


def test_snapshot_generator_creates_text_thumbnail_for_plain_text(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    object_dir = storage_root / "user-1" / "note.object"
    source_dir = object_dir / "original"
    source_dir.mkdir(parents=True)
    source_path = source_dir / "note.txt"
    source_path.write_text("Alpha\nBeta\nGamma\n", encoding="utf-8")

    content_object = ContentObject(
        id="object-1",
        owner_user_id="user-1",
        slug="note",
        title="Note",
        kind="simple",
        media_type="text",
        storage_path="user-1/note.object",
    )
    asset = ContentAsset(
        id="asset-1",
        content_object_id="object-1",
        role="original",
        media_type="text",
        filename="note.txt",
        mime_type="text/plain",
        size_bytes=source_path.stat().st_size,
        storage_path="user-1/note.object/original/note.txt",
    )

    thumbnail_text = SnapshotArtifactGenerator(storage_root).generate(
        content_object=content_object,
        asset=asset,
        job_type="thumbnail_text",
    )

    assert thumbnail_text.filename == "thumbnail.txt"
    assert thumbnail_text.mime_type == "text/plain"
    assert thumbnail_text.path.read_text(encoding="utf-8") == "Alpha\nBeta\nGamma\n"


def test_snapshot_generator_recognizes_pdf_by_mime_when_storage_key_lost_suffix(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"
    object_dir = storage_root / "user-1" / "pdf.object"
    source_dir = object_dir / "original"
    source_dir.mkdir(parents=True)
    source_path = source_dir / "original.bin"

    import fitz

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(fitz.Rect(48, 48, 547, 780), "PDF body", fontsize=12)
    doc.save(source_path)
    doc.close()

    content_object = ContentObject(
        id="object-1",
        owner_user_id="user-1",
        slug="pdf",
        title="PDF",
        kind="simple",
        media_type="document",
        storage_path="user-1/pdf.object",
    )
    asset = ContentAsset(
        id="asset-1",
        content_object_id="object-1",
        role="original",
        media_type="document",
        filename="дневничок.pdf",
        mime_type="application/pdf",
        size_bytes=source_path.stat().st_size,
        storage_path="user-1/pdf.object/original/original.bin",
    )
    generator = SnapshotArtifactGenerator(storage_root)

    thumbnail = generator.generate(content_object=content_object, asset=asset, job_type="thumbnail")
    markdown = generator.generate(content_object=content_object, asset=asset, job_type="markdown")

    assert thumbnail.filename == "thumbnail.jpg"
    assert thumbnail.mime_type == "image/jpeg"
    assert "PDF body" in markdown.path.read_text(encoding="utf-8")


def test_snapshot_generator_extracts_docx_markdown_and_skips_thumbnail_without_renderer(
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

    assert markdown.mime_type == "text/markdown"
    assert "First paragraph" in markdown.path.read_text(encoding="utf-8")
    assert "Second paragraph" in markdown.path.read_text(encoding="utf-8")
    with pytest.raises(UnsupportedSnapshotError, match="No thumbnail renderer"):
        generator.generate(content_object=content_object, asset=asset, job_type="thumbnail")
