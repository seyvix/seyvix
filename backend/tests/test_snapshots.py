from __future__ import annotations

import struct
import zipfile
import zlib
from pathlib import Path

import pytest
from app.modules.content.models import ContentAsset, ContentObject
from app.modules.snapshots.artifacts import (
    FetchedWebpage,
    GeneratedArtifact,
    SnapshotArtifactGenerator,
    UnsupportedSnapshotError,
)
from app.modules.snapshots.browser import BrowserSnapshot
from app.modules.snapshots.extraction.providers import (
    HttpVisionProvider,
    LocalWhisperSttProvider,
    OpenAICompatibleOcrProvider,
    OpenAICompatibleSttProvider,
    OpenAICompatibleVisionProvider,
)
from app.modules.snapshots.models import SnapshotJob
from app.modules.snapshots.service import EffectiveSnapshotSettings, plan_snapshot_job_types
from app.modules.snapshots.worker import extraction_metadata_from_generated_artifact
from app.platform.events.models import EventOutbox
from fastapi.testclient import TestClient
from sqlalchemy import select
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
        "available": [
            {
                "key": "screenshot",
                "label": "Screenshot",
                "description": "Visual webpage screenshot for link materials.",
                "server_enabled": True,
            },
            {
                "key": "webpage_html",
                "label": "HTML archive",
                "description": "Stored HTML copy of a linked webpage.",
                "server_enabled": False,
            },
            {
                "key": "pdf",
                "label": "PDF",
                "description": "PDF representation for documents, text files, and links.",
                "server_enabled": True,
            },
            {
                "key": "markdown",
                "label": "Markdown",
                "description": "Markdown text extracted from supported files and webpages.",
                "server_enabled": True,
            },
            {
                "key": "archive_org",
                "label": "Archive.org",
                "description": "External Internet Archive snapshot for link materials.",
                "server_enabled": False,
            },
        ],
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

    assert plan_snapshot_job_types(asset, settings) == ("markdown", "thumbnail_text", "pdf")


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

    assert plan_snapshot_job_types(asset, settings) == ("markdown", "thumbnail")


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
        "markdown",
        "thumbnail",
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

    assert plan_snapshot_job_types(asset, settings) == ("markdown", "thumbnail")


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

    stub_html = "<html><head><title>Research</title></head><body><h1>Hello</h1></body></html>"

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


def test_snapshot_generator_extracts_clean_structured_markdown_from_webpage(
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
    webpage = """
    <html>
      <head><title>Browser title</title></head>
      <body>
        <nav>Navigation should disappear</nav>
        <aside class="ad">Advertisement should disappear</aside>
        <div id="cookie-banner">Accept cookies should disappear</div>
        <article>
          <h1>Research article</h1>
          <p>Lead paragraph with <a href="https://example.com/docs">official docs</a>.</p>
          <ul><li>First finding</li><li>Second finding</li></ul>
          <blockquote>Quoted context</blockquote>
          <table><tr><th>Name</th><th>Score</th></tr><tr><td>Alpha</td><td>10</td></tr></table>
        </article>
        <script>window.tracker = true</script>
      </body>
    </html>
    """

    def fake_fetch(self: SnapshotArtifactGenerator, url: str) -> FetchedWebpage:
        assert url == "https://example.com/research"
        return FetchedWebpage(url=url, html=webpage)

    monkeypatch.setattr(SnapshotArtifactGenerator, "_fetch_webpage", fake_fetch)
    monkeypatch.setattr(
        "app.modules.snapshots.browser.render_url",
        lambda url: (_ for _ in ()).throw(RuntimeError("browser unavailable")),
    )

    generated = SnapshotArtifactGenerator(storage_root).generate(
        content_object=content_object,
        asset=asset,
        job_type="markdown",
    )
    markdown = generated.path.read_text(encoding="utf-8")

    assert "# Research article" in markdown
    assert "[official docs](https://example.com/docs)" in markdown
    assert "- First finding" in markdown
    assert "> Quoted context" in markdown
    assert "| Name | Score |" in markdown
    assert "Advertisement should disappear" not in markdown
    assert "Accept cookies should disappear" not in markdown
    assert "Navigation should disappear" not in markdown
    assert "window.tracker" not in markdown

    metadata = generated.path.with_suffix(".extraction.json")
    assert metadata.exists()
    assert '"source_kind": "webpage"' in metadata.read_text(encoding="utf-8")


def test_snapshot_generator_prefers_rendered_html_for_link_markdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "storage"
    object_dir = storage_root / "user-1" / "rendered.object"
    source_dir = object_dir / "original"
    source_dir.mkdir(parents=True)
    source_path = source_dir / "link.url"
    source_path.write_text("https://example.com/app", encoding="utf-8")

    content_object = ContentObject(
        id="object-1",
        owner_user_id="user-1",
        slug="rendered",
        title="Rendered",
        kind="simple",
        media_type="link",
        storage_path="user-1/rendered.object",
    )
    asset = ContentAsset(
        id="asset-1",
        content_object_id="object-1",
        role="original",
        media_type="link",
        filename="link.url",
        mime_type="text/uri-list",
        size_bytes=source_path.stat().st_size,
        storage_path="user-1/rendered.object/original/link.url",
        text_content="https://example.com/app",
    )

    def fake_fetch(self: SnapshotArtifactGenerator, url: str) -> FetchedWebpage:
        return FetchedWebpage(
            url=url, html="<html><body><article><h1>Raw HTML</h1></article></body></html>"
        )

    def fake_render_url(url: str) -> BrowserSnapshot:
        assert url == "https://example.com/app"
        return BrowserSnapshot(
            html=(
                "<html><body><article><h1>Rendered HTML</h1>"
                "<p>Client content</p></article></body></html>"
            ),
            screenshot_bytes=b"not-used",
        )

    monkeypatch.setattr(SnapshotArtifactGenerator, "_fetch_webpage", fake_fetch)
    monkeypatch.setattr("app.modules.snapshots.browser.render_url", fake_render_url)

    generated = SnapshotArtifactGenerator(storage_root).generate(
        content_object=content_object,
        asset=asset,
        job_type="markdown",
    )
    markdown = generated.path.read_text(encoding="utf-8")

    assert "Rendered HTML" in markdown
    assert "Client content" in markdown
    assert "Raw HTML" not in markdown


def test_worker_reads_extraction_metadata_from_generated_artifact(tmp_path: Path) -> None:
    artifact_path = tmp_path / "snapshot.md"
    metadata_path = tmp_path / "snapshot.extraction.json"
    artifact_path.write_text("# Snapshot", encoding="utf-8")
    metadata_path.write_text(
        '{"source_kind": "pdf", "method": "pdf", "warnings": ["pdf_text_ocr_mismatch"]}',
        encoding="utf-8",
    )
    generated = GeneratedArtifact(
        filename="snapshot.md",
        mime_type="text/markdown",
        path=artifact_path,
        metadata_path=metadata_path,
    )

    assert extraction_metadata_from_generated_artifact(generated) == {
        "source_kind": "pdf",
        "method": "pdf",
        "warnings": ["pdf_text_ocr_mismatch"],
    }


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


def test_snapshot_generator_uses_ocr_fallback_for_low_quality_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "storage"
    object_dir = storage_root / "user-1" / "scan.object"
    source_dir = object_dir / "original"
    source_dir.mkdir(parents=True)
    source_path = source_dir / "scan.pdf"

    import fitz

    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(source_path)
    doc.close()

    content_object = ContentObject(
        id="object-1",
        owner_user_id="user-1",
        slug="scan",
        title="Scan",
        kind="simple",
        media_type="document",
        storage_path="user-1/scan.object",
    )
    asset = ContentAsset(
        id="asset-1",
        content_object_id="object-1",
        role="original",
        media_type="document",
        filename="scan.pdf",
        mime_type="application/pdf",
        size_bytes=source_path.stat().st_size,
        storage_path="user-1/scan.object/original/scan.pdf",
    )

    class FakeOcrProvider:
        def extract_image_text(self, image_path: Path) -> str:
            assert image_path.exists()
            return "OCR page text from scanned PDF"

    monkeypatch.setattr(
        "app.modules.snapshots.extraction.dispatcher.build_ocr_provider",
        lambda: FakeOcrProvider(),
    )

    markdown = SnapshotArtifactGenerator(storage_root).generate(
        content_object=content_object,
        asset=asset,
        job_type="markdown",
    )

    assert "OCR page text from scanned PDF" in markdown.path.read_text(encoding="utf-8")
    metadata = markdown.path.with_suffix(".extraction.json").read_text(encoding="utf-8")
    assert '"method": "ocr"' in metadata


def test_snapshot_generator_reports_ocr_provider_failure_as_unsupported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "storage"
    object_dir = storage_root / "user-1" / "image.object"
    source_dir = object_dir / "original"
    source_dir.mkdir(parents=True)
    source_path = source_dir / "scan.png"
    source_path.write_bytes(_png_bytes(32, 32, (255, 255, 255)))

    content_object = ContentObject(
        id="object-1",
        owner_user_id="user-1",
        slug="image",
        title="Image",
        kind="simple",
        media_type="image",
        storage_path="user-1/image.object",
    )
    asset = ContentAsset(
        id="asset-1",
        content_object_id="object-1",
        role="original",
        media_type="image",
        filename="scan.png",
        mime_type="image/png",
        size_bytes=source_path.stat().st_size,
        storage_path="user-1/image.object/original/scan.png",
    )

    class BrokenOcrProvider:
        def extract_image_text(self, image_path: Path) -> str:
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        "app.modules.snapshots.extraction.dispatcher.build_ocr_provider",
        lambda: BrokenOcrProvider(),
    )

    with pytest.raises(UnsupportedSnapshotError, match="OCR provider failed"):
        SnapshotArtifactGenerator(storage_root).generate(
            content_object=content_object,
            asset=asset,
            job_type="markdown",
        )


def test_snapshot_generator_adds_image_description_to_markdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "storage"
    object_dir = storage_root / "user-1" / "image.object"
    source_dir = object_dir / "original"
    source_dir.mkdir(parents=True)
    source_path = source_dir / "diagram.png"
    source_path.write_bytes(_png_bytes(32, 32, (255, 255, 255)))

    content_object = ContentObject(
        id="object-1",
        owner_user_id="user-1",
        slug="image",
        title="Image",
        kind="simple",
        media_type="image",
        storage_path="user-1/image.object",
    )
    asset = ContentAsset(
        id="asset-1",
        content_object_id="object-1",
        role="original",
        media_type="image",
        filename="diagram.png",
        mime_type="image/png",
        size_bytes=source_path.stat().st_size,
        storage_path="user-1/image.object/original/diagram.png",
    )

    class FakeVisionProvider:
        def describe_image(self, image_path: Path) -> str:
            assert image_path.exists()
            return "A whiteboard diagram with database and worker boxes."

        def describe_video(self, video_path: Path, *, max_seconds: int) -> str | None:
            return None

    monkeypatch.setattr(
        "app.modules.snapshots.extraction.dispatcher.build_vision_provider",
        lambda: FakeVisionProvider(),
    )

    markdown = SnapshotArtifactGenerator(storage_root).generate(
        content_object=content_object,
        asset=asset,
        job_type="markdown",
    )

    text = markdown.path.read_text(encoding="utf-8")
    assert "## Image description" in text
    assert "A whiteboard diagram with database and worker boxes." in text
    metadata = markdown.path.with_suffix(".extraction.json").read_text(encoding="utf-8")
    assert '"method": "vision"' in metadata


def test_snapshot_generator_adds_video_description_with_duration_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "storage"
    object_dir = storage_root / "user-1" / "video.object"
    source_dir = object_dir / "original"
    source_dir.mkdir(parents=True)
    source_path = source_dir / "demo.mp4"
    source_path.write_bytes(b"fake video bytes")

    content_object = ContentObject(
        id="object-1",
        owner_user_id="user-1",
        slug="video",
        title="Video",
        kind="simple",
        media_type="video",
        storage_path="user-1/video.object",
    )
    asset = ContentAsset(
        id="asset-1",
        content_object_id="object-1",
        role="original",
        media_type="video",
        filename="demo.mp4",
        mime_type="video/mp4",
        size_bytes=source_path.stat().st_size,
        storage_path="user-1/video.object/original/demo.mp4",
    )

    class FakeVisionProvider:
        def describe_image(self, image_path: Path) -> str | None:
            return None

        def describe_video(self, video_path: Path, *, max_seconds: int) -> str:
            assert video_path.exists()
            assert max_seconds == 300
            return "The opening segment shows a product search workflow."

    monkeypatch.setattr(
        "app.modules.snapshots.extraction.dispatcher.build_vision_provider",
        lambda: FakeVisionProvider(),
    )

    markdown = SnapshotArtifactGenerator(storage_root).generate(
        content_object=content_object,
        asset=asset,
        job_type="markdown",
    )

    text = markdown.path.read_text(encoding="utf-8")
    assert "## Video description" in text
    assert "The opening segment shows a product search workflow." in text


def test_http_vision_provider_sends_video_duration_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake video")
    requests: list[dict[str, object]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"description": "A short demo clip."}

    def fake_post(url: str, *, json: dict[str, object], timeout: int) -> FakeResponse:
        requests.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("app.modules.snapshots.extraction.providers.httpx.post", fake_post)

    provider = HttpVisionProvider(endpoint_url="https://vision.example/extract", timeout_seconds=7)
    description = provider.describe_video(video_path, max_seconds=120)

    assert description == "A short demo clip."
    assert requests[0]["url"] == "https://vision.example/extract"
    assert requests[0]["timeout"] == 7
    payload = requests[0]["json"]
    assert isinstance(payload, dict)
    assert payload["kind"] == "video"
    assert payload["max_seconds"] == 120


def test_local_stt_provider_limits_ffmpeg_audio_extraction_duration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media_path = tmp_path / "clip.mp4"
    media_path.write_bytes(b"fake video")
    commands: list[list[str]] = []

    class FakeCompletedProcess:
        returncode = 0

    def fake_run(command: list[str], **kwargs: object) -> FakeCompletedProcess:
        commands.append(command)
        Path(command[-1]).write_bytes(b"fake wav")
        return FakeCompletedProcess()

    monkeypatch.setattr("app.modules.snapshots.extraction.providers.subprocess.run", fake_run)

    provider = LocalWhisperSttProvider(
        model_name="base",
        timeout_seconds=10,
        max_media_seconds=42,
    )
    audio_path = provider._extract_audio(media_path)

    assert audio_path is not None
    audio_path.unlink(missing_ok=True)
    assert "-t" in commands[0]
    assert commands[0][commands[0].index("-t") + 1] == "42"


def test_local_stt_provider_omits_ffmpeg_duration_limit_for_all_media(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media_path = tmp_path / "clip.mp4"
    media_path.write_bytes(b"fake video")
    commands: list[list[str]] = []

    class FakeCompletedProcess:
        returncode = 0

    def fake_run(command: list[str], **kwargs: object) -> FakeCompletedProcess:
        commands.append(command)
        Path(command[-1]).write_bytes(b"fake wav")
        return FakeCompletedProcess()

    monkeypatch.setattr("app.modules.snapshots.extraction.providers.subprocess.run", fake_run)

    provider = LocalWhisperSttProvider(
        model_name="base",
        timeout_seconds=10,
        max_media_seconds=-1,
    )
    audio_path = provider._extract_audio(media_path)

    assert audio_path is not None
    audio_path.unlink(missing_ok=True)
    assert "-t" not in commands[0]


def test_openai_compatible_ocr_provider_posts_image_to_chat_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = tmp_path / "scan.png"
    image_path.write_bytes(_png_bytes(4, 4, (255, 255, 255)))
    requests: list[dict[str, object]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": "Recognized text"}}]}

    def fake_post(
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
        timeout: int,
    ) -> FakeResponse:
        requests.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("app.modules.snapshots.extraction.providers.httpx.post", fake_post)

    provider = OpenAICompatibleOcrProvider(
        base_url="https://llm.example/v1",
        api_key="secret",
        model="vision-ocr",
        timeout_seconds=9,
        max_image_bytes=100_000,
    )

    assert provider.extract_image_text(image_path) == "Recognized text"
    assert requests[0]["url"] == "https://llm.example/v1/chat/completions"
    assert requests[0]["headers"] == {"Authorization": "Bearer secret"}
    payload = requests[0]["json"]
    assert isinstance(payload, dict)
    assert payload["model"] == "vision-ocr"


def test_openai_compatible_stt_provider_transcribes_audio_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media_path = tmp_path / "lecture.mp4"
    media_path.write_bytes(b"fake video")
    first_chunk = tmp_path / "chunk-1.wav"
    second_chunk = tmp_path / "chunk-2.wav"
    first_chunk.write_bytes(b"first")
    second_chunk.write_bytes(b"second")
    requests: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, text: str) -> None:
            self.text = text

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"text": self.text}

    responses = [FakeResponse("first transcript"), FakeResponse("second transcript")]

    def fake_chunks(self: OpenAICompatibleSttProvider, source_path: Path) -> list[Path]:
        assert source_path == media_path
        return [first_chunk, second_chunk]

    def fake_post(
        url: str,
        *,
        headers: dict[str, str],
        data: dict[str, str],
        files: dict[str, tuple[str, object, str]],
        timeout: int,
    ) -> FakeResponse:
        requests.append({"url": url, "headers": headers, "data": data, "files": files})
        return responses.pop(0)

    monkeypatch.setattr(OpenAICompatibleSttProvider, "_extract_audio_chunks", fake_chunks)
    monkeypatch.setattr("app.modules.snapshots.extraction.providers.httpx.post", fake_post)

    provider = OpenAICompatibleSttProvider(
        base_url="https://llm.example/v1",
        api_key="secret",
        model="whisper-large-v3",
        timeout_seconds=10,
        max_media_seconds=-1,
        chunk_seconds=600,
    )

    assert provider.transcribe_media(media_path) == "first transcript\n\nsecond transcript"
    assert len(requests) == 2
    assert requests[0]["url"] == "https://llm.example/v1/audio/transcriptions"
    assert requests[0]["data"] == {"model": "whisper-large-v3"}


def test_openai_compatible_vision_provider_describes_video_in_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video_path = tmp_path / "demo.mp4"
    video_path.write_bytes(b"fake video")
    requested_ranges: list[tuple[int, int]] = []

    class FakeResponse:
        def __init__(self, text: str) -> None:
            self.text = text

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": self.text}}]}

    responses = [FakeResponse("first minute"), FakeResponse("second minute")]

    def fake_duration(self: OpenAICompatibleVisionProvider, video_path: Path) -> float:
        return 600.0

    def fake_frames(
        self: OpenAICompatibleVisionProvider,
        source_path: Path,
        *,
        start_seconds: int,
        duration_seconds: int,
    ) -> list[Path]:
        requested_ranges.append((start_seconds, duration_seconds))
        frame_path = tmp_path / f"frame-{start_seconds}.jpg"
        frame_path.write_bytes(b"fake frame")
        return [frame_path]

    def fake_post(
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
        timeout: int,
    ) -> FakeResponse:
        return responses.pop(0)

    monkeypatch.setattr(OpenAICompatibleVisionProvider, "_probe_duration_seconds", fake_duration)
    monkeypatch.setattr(OpenAICompatibleVisionProvider, "_extract_video_frames", fake_frames)
    monkeypatch.setattr("app.modules.snapshots.extraction.providers.httpx.post", fake_post)

    provider = OpenAICompatibleVisionProvider(
        base_url="https://llm.example/v1",
        api_key="secret",
        model="vision-model",
        timeout_seconds=10,
        max_image_bytes=100_000,
        video_chunk_seconds=60,
        video_frame_interval_seconds=15,
        max_frames_per_request=4,
    )

    description = provider.describe_video(video_path, max_seconds=120)

    assert requested_ranges == [(0, 60), (60, 60)]
    assert description == "Chunk 1 (0-60s): first minute\n\nChunk 2 (60-120s): second minute"


def test_openai_compatible_vision_provider_processes_all_video_when_limit_is_negative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video_path = tmp_path / "full.mp4"
    video_path.write_bytes(b"fake video")
    requested_ranges: list[tuple[int, int]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": "chunk"}}]}

    def fake_duration(self: OpenAICompatibleVisionProvider, video_path: Path) -> float:
        return 125.0

    def fake_frames(
        self: OpenAICompatibleVisionProvider,
        source_path: Path,
        *,
        start_seconds: int,
        duration_seconds: int,
    ) -> list[Path]:
        requested_ranges.append((start_seconds, duration_seconds))
        frame_path = tmp_path / f"full-frame-{start_seconds}.jpg"
        frame_path.write_bytes(b"fake frame")
        return [frame_path]

    def fake_post(
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
        timeout: int,
    ) -> FakeResponse:
        return FakeResponse()

    monkeypatch.setattr(OpenAICompatibleVisionProvider, "_probe_duration_seconds", fake_duration)
    monkeypatch.setattr(OpenAICompatibleVisionProvider, "_extract_video_frames", fake_frames)
    monkeypatch.setattr("app.modules.snapshots.extraction.providers.httpx.post", fake_post)

    provider = OpenAICompatibleVisionProvider(
        base_url="https://llm.example/v1",
        api_key=None,
        model="vision-model",
        timeout_seconds=10,
        max_image_bytes=100_000,
        video_chunk_seconds=60,
        video_frame_interval_seconds=15,
        max_frames_per_request=4,
    )

    provider.describe_video(video_path, max_seconds=-1)

    assert requested_ranges == [(0, 60), (60, 60), (120, 5)]


def test_snapshot_generator_records_pdf_text_ocr_mismatch_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "storage"
    object_dir = storage_root / "user-1" / "mismatch.object"
    source_dir = object_dir / "original"
    source_dir.mkdir(parents=True)
    source_path = source_dir / "mismatch.pdf"

    import fitz

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(fitz.Rect(48, 48, 547, 780), "bad text", fontsize=12)
    doc.save(source_path)
    doc.close()

    content_object = ContentObject(
        id="object-1",
        owner_user_id="user-1",
        slug="mismatch",
        title="Mismatch",
        kind="simple",
        media_type="document",
        storage_path="user-1/mismatch.object",
    )
    asset = ContentAsset(
        id="asset-1",
        content_object_id="object-1",
        role="original",
        media_type="document",
        filename="mismatch.pdf",
        mime_type="application/pdf",
        size_bytes=source_path.stat().st_size,
        storage_path="user-1/mismatch.object/original/mismatch.pdf",
    )

    class FakeOcrProvider:
        def extract_image_text(self, image_path: Path) -> str:
            assert image_path.exists()
            return "OCR text says the invoice total is one hundred dollars"

    monkeypatch.setattr(
        "app.modules.snapshots.extraction.dispatcher.build_ocr_provider",
        lambda: FakeOcrProvider(),
    )

    markdown = SnapshotArtifactGenerator(storage_root).generate(
        content_object=content_object,
        asset=asset,
        job_type="markdown",
    )

    metadata = markdown.path.with_suffix(".extraction.json").read_text(encoding="utf-8")
    assert "pdf_text_ocr_mismatch" in metadata
    assert "embedded PDF text differs from OCR text" in metadata


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
    with pytest.raises(UnsupportedSnapshotError, match="Конвертер офисных файлов недоступен"):
        generator.generate(content_object=content_object, asset=asset, job_type="thumbnail")


def test_snapshot_generator_extracts_docx_tables_as_markdown(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    object_dir = storage_root / "user-1" / "table-doc.object"
    source_dir = object_dir / "original"
    source_dir.mkdir(parents=True)
    docx_path = source_dir / "table-report.docx"
    with zipfile.ZipFile(docx_path, "w") as archive:
        archive.writestr(
            "word/document.xml",
            (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body>"
                "<w:p><w:r><w:t>Intro paragraph</w:t></w:r></w:p>"
                "<w:tbl>"
                "<w:tr><w:tc><w:p><w:r><w:t>Name</w:t></w:r></w:p></w:tc>"
                "<w:tc><w:p><w:r><w:t>Score</w:t></w:r></w:p></w:tc></w:tr>"
                "<w:tr><w:tc><w:p><w:r><w:t>Alpha</w:t></w:r></w:p></w:tc>"
                "<w:tc><w:p><w:r><w:t>10</w:t></w:r></w:p></w:tc></w:tr>"
                "</w:tbl>"
                "</w:body></w:document>"
            ),
        )

    content_object = ContentObject(
        id="object-1",
        owner_user_id="user-1",
        slug="table-doc",
        title="Table document",
        kind="simple",
        media_type="document",
        storage_path="user-1/table-doc.object",
    )
    asset = ContentAsset(
        id="asset-1",
        content_object_id="object-1",
        role="original",
        media_type="document",
        filename="table-report.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes=docx_path.stat().st_size,
        storage_path="user-1/table-doc.object/original/table-report.docx",
    )

    markdown = SnapshotArtifactGenerator(storage_root).generate(
        content_object=content_object,
        asset=asset,
        job_type="markdown",
    )
    text = markdown.path.read_text(encoding="utf-8")

    assert "Intro paragraph" in text
    assert "| Name | Score |" in text
    assert "| Alpha | 10 |" in text


def test_snapshot_reprocess_endpoint_queues_markdown_for_existing_asset(
    content_client: TestClient,
) -> None:
    headers = _auth_headers(content_client)
    upload_response = content_client.post(
        "/api/v1/notes/file/upload",
        headers=headers,
        data={"create_object": "true"},
        files={"file": ("report.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")},
    )
    assert upload_response.status_code == 201, upload_response.text
    note = upload_response.json()
    asset_id = note["objects"][0]["id"]

    response = content_client.post(
        "/api/v1/snapshots/reprocess",
        headers=headers,
        json={"content_object_id": note["id"]},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["queued_count"] == 1
    assert payload["job_ids"]
    assert payload["source_asset_ids"] == [asset_id]

    async def load_job() -> SnapshotJob | None:
        async with content_client.app.state.session_factory() as session:
            return await session.scalar(
                select(SnapshotJob).where(
                    SnapshotJob.source_asset_id == asset_id,
                    SnapshotJob.job_type == "markdown",
                )
            )

    job = content_client.portal.call(load_job)
    assert job is not None
    assert job.status == "pending"


def test_office_failure_message_iwork_export_hint() -> None:
    from app.modules.snapshots.extraction.office import (
        OfficeConversionResult,
        office_failure_message,
    )

    msg = office_failure_message(
        asset_filename="deck.key",
        result=OfficeConversionResult(pdf_path=None, failure_kind="exit_error", stderr_tail="boom"),
        timeout_seconds=90,
    )
    assert "Keynote" in msg
    assert "PDF" in msg


def test_office_failure_message_timeout_mentions_seconds() -> None:
    from app.modules.snapshots.extraction.office import (
        OfficeConversionResult,
        office_failure_message,
    )

    msg = office_failure_message(
        asset_filename="huge.pptx",
        result=OfficeConversionResult(pdf_path=None, failure_kind="timeout"),
        timeout_seconds=42,
    )
    assert "42" in msg


def test_office_failure_message_no_command_is_server_side() -> None:
    from app.modules.snapshots.extraction.office import (
        OfficeConversionResult,
        office_failure_message,
    )

    msg = office_failure_message(
        asset_filename="report.docx",
        result=OfficeConversionResult(pdf_path=None, failure_kind="no_command"),
        timeout_seconds=90,
    )
    assert "сервере" in msg.lower()


def test_office_failure_message_generic_for_non_iwork_exit_error() -> None:
    from app.modules.snapshots.extraction.office import (
        OfficeConversionResult,
        office_failure_message,
    )

    msg = office_failure_message(
        asset_filename="report.docx",
        result=OfficeConversionResult(pdf_path=None, failure_kind="exit_error"),
        timeout_seconds=90,
    )
    assert ".pdf" in msg.lower()
    assert "keynote" not in msg.lower()


def test_convert_office_to_pdf_returns_no_command_when_setting_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.core.config import get_settings
    from app.modules.snapshots.artifacts import SnapshotArtifactGenerator

    settings = get_settings()
    monkeypatch.setattr(settings, "snapshot_office_converter_command", None)

    source = tmp_path / "doc.docx"
    source.write_bytes(b"not really a docx")

    result = SnapshotArtifactGenerator._convert_office_to_pdf(source)
    assert result.pdf_path is None
    assert result.failure_kind == "no_command"


def test_convert_office_to_pdf_returns_no_output_when_subprocess_succeeds_silently(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """LibreOffice can exit 0 but never write a PDF (libetonyek on a modern
    .key is the real-world trigger)."""
    import subprocess as subprocess_mod
    from app.modules.snapshots import artifacts as artifacts_mod
    from app.modules.snapshots.artifacts import SnapshotArtifactGenerator

    def _fake_run(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return subprocess_mod.CompletedProcess(
            args=_args[0] if _args else [],
            returncode=0,
            stdout="",
            stderr="libetonyek: unsupported version\n",
        )

    monkeypatch.setattr(artifacts_mod.subprocess, "run", _fake_run)

    source = tmp_path / "modern.key"
    source.write_bytes(b"fake-key-payload")

    result = SnapshotArtifactGenerator._convert_office_to_pdf(source)
    assert result.pdf_path is None
    assert result.failure_kind == "no_output"
    assert "libetonyek" in result.stderr_tail
