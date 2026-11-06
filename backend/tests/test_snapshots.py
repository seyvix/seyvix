from __future__ import annotations

import asyncio
import os
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz
import httpx
import pytest
from PIL import Image

from app.core.config import Settings
from app.modules.llm.client import AIResponseError, AIUnavailableError
from app.modules.snapshots.artifacts import GeneratedArtifact, SnapshotGenerator, SourceAsset
from app.modules.snapshots.browser import PageCapture, RenderRequest
from app.modules.snapshots.egress import (
    BlockedDestinationError,
    EgressProxy,
    FetchError,
    fetch_html,
    is_public_address,
    parse_public_url,
)
from app.modules.snapshots.errors import SnapshotError
from app.modules.snapshots.extraction.ai import AIEnrichment
from app.modules.snapshots.extraction.html import html_to_markdown
from app.modules.snapshots.extraction.office import (
    OfficeConversionResult,
    convert_office_to_pdf,
    office_failure_message,
)
from app.modules.snapshots.planning import (
    AssetFacts,
    EffectiveSnapshotSettings,
    plan_snapshot_job_types,
    source_fingerprint,
    text_extractable,
)
from app.modules.snapshots.processes import ProcessTimeoutError, run_process
from app.modules.snapshots.rewriter import mime_for_resource, rewrite_html
from app.modules.snapshots.service import api_job_status, artifact_dir
from app.platform.storage.local import LocalVolumeStorage

ALL_ON = EffectiveSnapshotSettings(screenshot=True, webpage_html=True, pdf=True, markdown=True)


# --- fakes ----------------------------------------------------------------------------------
@dataclass
class FakeBrowser:
    html: str = "<html><body><article><h1>Title</h1><p>Body text</p></article></body></html>"
    error: SnapshotError | None = None
    calls: list[RenderRequest] = field(default_factory=list)

    async def render(self, request: RenderRequest) -> PageCapture:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        capture = PageCapture(url=request.url, html=self.html)
        if request.screenshot or request.full_page:
            capture.screenshot = request.out_dir / "screenshot.jpg"
            Image.new("RGB", (1280, 2400), "white").save(capture.screenshot, format="JPEG")
        if request.pdf:
            capture.pdf = request.out_dir / "page.pdf"
            with fitz.open() as doc:
                doc.new_page()
                doc.save(str(capture.pdf))
        return capture

    async def aclose(self) -> None:
        return None


@dataclass
class FakeAI:
    ocr_text: str = "Recognized text from the scanned page with plenty of real words in it"
    description: str = "A diagram of a system"
    unavailable: bool = False
    calls: list[str] = field(default_factory=list)

    async def describe_image(
        self, image: bytes, mime_type: str, prompt: str, *, model: str | None = None
    ) -> str:
        self.calls.append("ocr" if prompt.startswith("Extract") else "describe")
        if self.unavailable:
            raise AIUnavailableError("provider down")
        return self.ocr_text if prompt.startswith("Extract") else self.description

    async def chat_text(self, messages: list[dict[str, Any]], **_: Any) -> str:
        self.calls.append("frames")
        return "video segment"

    async def transcribe(self, audio_path: Path, *, language: str | None = None) -> str:
        self.calls.append("transcribe")
        return "spoken words"


def _ai(fake: FakeAI | None = None, *, ocr: bool = True, vision: bool = True) -> AIEnrichment:
    return AIEnrichment(
        client=fake,  # type: ignore[arg-type]
        ocr_enabled=fake is not None and ocr,
        vision_enabled=fake is not None and vision,
        transcription_enabled=fake is not None,
        vision_model="vision",
    )


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"snapshot_office_converter_command": ""}
    values.update(overrides)
    return Settings(**values)


def _generator(
    tmp_path: Path,
    *,
    browser: FakeBrowser | None = None,
    ai: AIEnrichment | None = None,
    settings: Settings | None = None,
) -> tuple[SnapshotGenerator, LocalVolumeStorage]:
    storage = LocalVolumeStorage(tmp_path / "storage")
    generator = SnapshotGenerator(
        settings or _settings(),
        storage,
        browser or FakeBrowser(),  # type: ignore[arg-type]
        EgressProxy(),
        ai or _ai(),
    )
    return generator, storage


async def _asset(
    storage: LocalVolumeStorage,
    *,
    filename: str,
    media_type: str,
    mime_type: str | None,
    data: bytes,
    text_content: str | None = None,
) -> SourceAsset:
    key = f"objects/obj-1/assets/asset-1/original{Path(filename).suffix or '.bin'}"
    await storage.put_bytes(key, data, mime_type)
    return SourceAsset(
        id="asset-1",
        content_object_id="obj-1",
        media_type=media_type,
        mime_type=mime_type,
        filename=filename,
        storage_key=key,
        text_content=text_content,
    )


async def _generate(
    generator: SnapshotGenerator, asset: SourceAsset, job_types: list[str], work: Path
) -> dict[str, GeneratedArtifact | SnapshotError]:
    work.mkdir(parents=True, exist_ok=True)
    return await generator.generate(
        asset, job_types, work, artifact_ids={job_type: f"art-{job_type}" for job_type in job_types}
    )


def _ok(outcome: GeneratedArtifact | SnapshotError) -> GeneratedArtifact:
    assert isinstance(outcome, GeneratedArtifact), outcome
    return outcome


def _pdf_bytes(pages: list[str]) -> bytes:
    with fitz.open() as doc:
        for text in pages:
            page = doc.new_page()
            if text:
                page.insert_text((72, 72), text)
        return doc.tobytes()


# --- planning -------------------------------------------------------------------------------
def test_plan_text_note_uses_text_thumbnail_and_pdf() -> None:
    facts = AssetFacts("text", "text/markdown", "note.md")
    assert plan_snapshot_job_types(facts, ALL_ON) == ("markdown", "thumbnail_text", "pdf")


def test_plan_skips_pdf_for_existing_pdf() -> None:
    facts = AssetFacts("document", "application/pdf", "report.pdf")
    assert plan_snapshot_job_types(facts, ALL_ON) == ("markdown", "thumbnail")


def test_plan_link_includes_site_outputs_when_enabled() -> None:
    facts = AssetFacts("link", "text/uri-list", "link.url")
    assert plan_snapshot_job_types(facts, ALL_ON) == (
        "markdown", "thumbnail", "pdf", "screenshot", "webpage_html",
    )  # fmt: skip


def test_plan_respects_disabled_pdf_but_always_extracts_text() -> None:
    facts = AssetFacts(
        "document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "slides.pptx",
    )
    disabled = EffectiveSnapshotSettings(
        screenshot=True, webpage_html=True, pdf=False, markdown=False
    )
    assert plan_snapshot_job_types(facts, disabled) == ("markdown", "thumbnail")


def test_images_and_media_get_no_text_job_without_ai() -> None:
    image = AssetFacts("image", "image/png", "photo.png")
    assert not text_extractable(image, _settings(ai_api_key=None))
    assert text_extractable(image, _settings(ai_api_key="key", ai_ocr_enabled=True))
    assert plan_snapshot_job_types(image, ALL_ON, extract_text=False) == ("thumbnail",)
    assert text_extractable(AssetFacts("document", "application/pdf", "a.pdf"), _settings())


def test_fingerprint_changes_with_source() -> None:
    base = {"storage_key": "k", "size_bytes": 1, "checksum": "c", "text_content": "a"}
    assert source_fingerprint(**base) == source_fingerprint(**base)
    assert source_fingerprint(**base) != source_fingerprint(**{**base, "text_content": "b"})


def test_api_job_status_keeps_web_contract() -> None:
    assert api_job_status("succeeded") == "done"
    assert api_job_status("failed") == "failed"
    assert artifact_dir("objects/o/assets/a/snapshots/pdf/x/snapshot.pdf") == (
        "objects/o/assets/a/snapshots/pdf/x/"
    )


# --- generation -----------------------------------------------------------------------------
async def test_image_thumbnail_is_bounded_webp(tmp_path: Path) -> None:
    generator, storage = _generator(tmp_path)
    buffer = tmp_path / "big.png"
    Image.new("RGB", (2400, 1200), "blue").save(buffer)
    asset = await _asset(
        storage,
        filename="photo.png",
        media_type="image",
        mime_type="image/png",
        data=buffer.read_bytes(),
    )

    outcomes = await _generate(generator, asset, ["thumbnail"], tmp_path / "work")

    thumbnail = _ok(outcomes["thumbnail"])
    assert thumbnail.mime_type == "image/webp"
    assert thumbnail.path is not None
    with Image.open(thumbnail.path) as image:
        assert image.format == "WEBP"
        assert max(image.size) <= 512


async def test_text_note_produces_markdown_inline_preview_and_pdf(tmp_path: Path) -> None:
    generator, storage = _generator(tmp_path)
    text = "# Заголовок\n\nПервая строка заметки.\n\n\n\nВторая."
    asset = await _asset(
        storage,
        filename="note.md",
        media_type="text",
        mime_type="text/markdown",
        data=text.encode(),
        text_content=text,
    )

    outcomes = await _generate(
        generator, asset, ["markdown", "thumbnail_text", "pdf"], tmp_path / "work"
    )

    markdown = _ok(outcomes["markdown"])
    assert markdown.path is not None
    assert "Первая строка заметки." in markdown.path.read_text(encoding="utf-8")
    assert markdown.metadata["extraction"]["method"] == "markdown"
    preview = _ok(outcomes["thumbnail_text"])
    assert preview.path is None and preview.text is not None and "Вторая." in preview.text
    pdf = _ok(outcomes["pdf"])
    assert pdf.path is not None
    with fitz.open(str(pdf.path)) as doc:
        assert "Первая строка" in doc[0].get_text()


async def test_csv_thumbnail_renders_text_preview(tmp_path: Path) -> None:
    generator, storage = _generator(tmp_path)
    asset = await _asset(
        storage,
        filename="table.csv",
        media_type="document",
        mime_type="text/csv",
        data=b"name,value\nalpha,1\n",
    )

    outcomes = await _generate(generator, asset, ["thumbnail", "markdown"], tmp_path / "work")

    assert _ok(outcomes["thumbnail"]).mime_type == "image/webp"
    markdown = _ok(outcomes["markdown"])
    assert markdown.path is not None
    assert "| name | value |" in markdown.path.read_text(encoding="utf-8")


async def test_link_renders_page_once_for_all_outputs(tmp_path: Path) -> None:
    browser = FakeBrowser()
    generator, storage = _generator(tmp_path, browser=browser)
    asset = await _asset(
        storage,
        filename="link.url",
        media_type="link",
        mime_type="text/uri-list",
        data=b"https://example.com/a",
        text_content="https://example.com/a",
    )

    outcomes = await _generate(
        generator,
        asset,
        ["markdown", "thumbnail", "screenshot", "pdf", "webpage_html"],
        tmp_path / "work",
    )

    assert len(browser.calls) == 1
    request = browser.calls[0]
    assert request.html and request.screenshot and request.full_page and request.pdf
    assert request.archive
    assert _ok(outcomes["thumbnail"]).mime_type == "image/webp"
    assert _ok(outcomes["screenshot"]).mime_type == "image/jpeg"
    assert _ok(outcomes["pdf"]).mime_type == "application/pdf"
    markdown_path = _ok(outcomes["markdown"]).path
    assert markdown_path is not None and "Body text" in markdown_path.read_text()
    html_path = _ok(outcomes["webpage_html"]).path
    assert html_path is not None and "Body text" in html_path.read_text()


async def test_link_render_failure_is_retryable_for_visual_outputs(tmp_path: Path) -> None:
    browser = FakeBrowser(error=SnapshotError("Page could not be loaded", retryable=True))
    generator, storage = _generator(tmp_path, browser=browser)
    asset = await _asset(
        storage,
        filename="link.url",
        media_type="link",
        mime_type="text/uri-list",
        data=b"",
        text_content="https://example.com/",
    )

    outcomes = await _generate(generator, asset, ["thumbnail", "pdf"], tmp_path / "work")

    for job_type in ("thumbnail", "pdf"):
        error = outcomes[job_type]
        assert isinstance(error, SnapshotError) and error.retryable
    assert len(browser.calls) == 1  # the failed render is not repeated per output


async def test_link_with_private_url_is_rejected_for_markdown(tmp_path: Path) -> None:
    browser = FakeBrowser(error=SnapshotError("blocked"))
    generator, storage = _generator(tmp_path, browser=browser)
    asset = await _asset(
        storage,
        filename="link.url",
        media_type="link",
        mime_type="text/uri-list",
        data=b"",
        text_content="ftp://example.com",
    )

    outcomes = await _generate(generator, asset, ["markdown"], tmp_path / "work")

    error = outcomes["markdown"]
    assert isinstance(error, SnapshotError) and not error.retryable
    assert browser.calls == []


async def test_pdf_low_quality_pages_use_ai_ocr(tmp_path: Path) -> None:
    fake = FakeAI()
    generator, storage = _generator(tmp_path, ai=_ai(fake))
    asset = await _asset(
        storage,
        filename="scan.pdf",
        media_type="document",
        mime_type="application/pdf",
        data=_pdf_bytes([""]),
    )

    outcomes = await _generate(generator, asset, ["markdown", "thumbnail"], tmp_path / "work")

    markdown = _ok(outcomes["markdown"])
    assert markdown.path is not None
    assert "Recognized text" in markdown.path.read_text()
    assert markdown.metadata["extraction"]["pages"][0]["method"] == "ocr"
    assert fake.calls == ["ocr"]
    assert _ok(outcomes["thumbnail"]).mime_type == "image/webp"


async def test_ai_unavailable_makes_text_job_retryable_without_failing_others(
    tmp_path: Path,
) -> None:
    generator, storage = _generator(tmp_path, ai=_ai(FakeAI(unavailable=True)))
    asset = await _asset(
        storage,
        filename="scan.pdf",
        media_type="document",
        mime_type="application/pdf",
        data=_pdf_bytes([""]),
    )

    outcomes = await _generate(generator, asset, ["markdown", "thumbnail"], tmp_path / "work")

    error = outcomes["markdown"]
    assert isinstance(error, SnapshotError) and error.retryable
    _ok(outcomes["thumbnail"])


async def test_pdf_without_ai_reports_missing_text(tmp_path: Path) -> None:
    generator, storage = _generator(tmp_path, ai=_ai(None))
    asset = await _asset(
        storage,
        filename="scan.pdf",
        media_type="document",
        mime_type="application/pdf",
        data=_pdf_bytes([""]),
    )

    outcomes = await _generate(generator, asset, ["markdown"], tmp_path / "work")

    error = outcomes["markdown"]
    assert isinstance(error, SnapshotError) and not error.retryable


async def test_image_markdown_combines_description_and_ocr(tmp_path: Path) -> None:
    fake = FakeAI(ocr_text="STOP sign")
    generator, storage = _generator(tmp_path, ai=_ai(fake))
    buffer = tmp_path / "img.png"
    Image.new("RGB", (64, 64), "red").save(buffer)
    asset = await _asset(
        storage,
        filename="img.png",
        media_type="image",
        mime_type="image/png",
        data=buffer.read_bytes(),
    )

    outcomes = await _generate(generator, asset, ["markdown"], tmp_path / "work")

    path = _ok(outcomes["markdown"]).path
    assert path is not None
    text = path.read_text()
    assert "## Image description" in text and "A diagram of a system" in text
    assert "## OCR text" in text and "STOP sign" in text


async def test_image_ai_response_error_degrades_gracefully(tmp_path: Path) -> None:
    class Rejecting(FakeAI):
        async def describe_image(self, *args: Any, **kwargs: Any) -> str:
            raise AIResponseError("unsupported image")

    generator, storage = _generator(tmp_path, ai=_ai(Rejecting()))
    buffer = tmp_path / "img.png"
    Image.new("RGB", (8, 8), "red").save(buffer)
    asset = await _asset(
        storage,
        filename="img.png",
        media_type="image",
        mime_type="image/png",
        data=buffer.read_bytes(),
    )

    outcomes = await _generate(generator, asset, ["markdown"], tmp_path / "work")

    error = outcomes["markdown"]
    assert isinstance(error, SnapshotError) and not error.retryable
    assert "unsupported image" in str(error)


async def test_docx_markdown_keeps_tables(tmp_path: Path) -> None:
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    document = (
        f'<w:document xmlns:w="{namespace}"><w:body>'
        "<w:p><w:r><w:t>Intro</w:t></w:r></w:p>"
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>A</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>B</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
        "</w:body></w:document>"
    )
    docx = tmp_path / "doc.docx"
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("word/document.xml", document)
    generator, storage = _generator(tmp_path)
    asset = await _asset(
        storage, filename="doc.docx", media_type="document",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        data=docx.read_bytes(),
    )  # fmt: skip

    outcomes = await _generate(generator, asset, ["markdown", "thumbnail"], tmp_path / "work")

    path = _ok(outcomes["markdown"]).path
    assert path is not None
    assert "Intro" in path.read_text() and "| A | B |" in path.read_text()
    # No office converter configured: the thumbnail fails permanently with a clear message.
    error = outcomes["thumbnail"]
    assert isinstance(error, SnapshotError) and not error.retryable
    assert "недоступен" in str(error)


async def test_unexpected_errors_are_contained(tmp_path: Path) -> None:
    generator, storage = _generator(tmp_path)
    asset = await _asset(
        storage, filename="x.bin", media_type="document", mime_type=None, data=b"x"
    )

    outcomes = await _generate(generator, asset, ["bogus"], tmp_path / "work")

    assert isinstance(outcomes["bogus"], SnapshotError)


# --- office / processes ---------------------------------------------------------------------
async def test_office_conversion_reports_missing_command(tmp_path: Path) -> None:
    result = await convert_office_to_pdf(tmp_path / "a.docx", tmp_path, _settings())
    assert result == OfficeConversionResult(None, "no_command")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
async def test_office_conversion_timeout_kills_process_group(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    script = tmp_path / "fake-soffice"
    script.write_text(f"#!/bin/sh\nsleep 30 &\necho $! > {pid_file}\nwait\n")
    script.chmod(0o755)
    source = tmp_path / "a.docx"
    source.write_bytes(b"x")
    settings = _settings(
        snapshot_office_converter_command=str(script),
        snapshot_office_converter_timeout_seconds=3,
    )

    result = await convert_office_to_pdf(source, tmp_path, settings)

    assert result.failure_kind == "timeout"
    child = int(pid_file.read_text())
    await asyncio.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)


async def test_run_process_times_out() -> None:
    started = time.monotonic()
    with pytest.raises(ProcessTimeoutError):
        await run_process(["sleep", "10"], timeout=0.5)
    assert time.monotonic() - started < 5


def test_office_failure_messages() -> None:
    iwork = office_failure_message(
        asset_filename="deck.key",
        result=OfficeConversionResult(None, "exit_error"),
        timeout_seconds=90,
    )
    assert "Keynote" in iwork
    timeout = office_failure_message(
        asset_filename="a.docx",
        result=OfficeConversionResult(None, "timeout"),
        timeout_seconds=90,
    )
    assert "90" in timeout


# --- network guard --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "http://localhost/", "http://foo.localhost/", "gopher://x"],
)
def test_parse_public_url_rejects_local_and_non_http(url: str) -> None:
    with pytest.raises(BlockedDestinationError):
        parse_public_url(url)


def test_public_address_classification() -> None:
    import ipaddress

    for blocked in (
        "127.0.0.1",
        "10.1.2.3",
        "169.254.169.254",
        "100.64.0.1",
        "::1",
        "::ffff:127.0.0.1",
        "fd00::1",
        "0.0.0.0",
    ):
        assert not is_public_address(ipaddress.ip_address(blocked)), blocked
    assert is_public_address(ipaddress.ip_address("93.184.216.34"))


async def test_fetch_refuses_private_destinations() -> None:
    proxy = EgressProxy()
    try:
        with pytest.raises((BlockedDestinationError, FetchError)):
            await fetch_html("http://127.0.0.1:9/", proxy)
        async with httpx.AsyncClient(proxy=await proxy.url()) as client:
            response = await client.get("http://10.0.0.1/")
        assert response.status_code == 403
    finally:
        await proxy.aclose()


# --- html -----------------------------------------------------------------------------------
def test_html_to_markdown_skips_boilerplate() -> None:
    result = html_to_markdown(
        "<html><body><nav>Menu</nav><div class='cookie-banner'>Accept</div>"
        "<article><h1>Title</h1><p>Hello <a href='/x'>link</a></p></article></body></html>",
        source_url="https://example.com/",
    )
    assert "# Title" in result.markdown
    assert "[link](https://example.com/x)" in result.markdown
    assert "Menu" not in result.markdown and "Accept" not in result.markdown


def test_rewrite_html_strips_scripts_and_maps_resources() -> None:
    html = (
        "<html><head><link rel='stylesheet' href='/s.css'><script>alert(1)</script></head>"
        "<body onload='x()'><img src='a.png'></body></html>"
    )
    manifest = {
        "https://example.com/s.css": "/api/r0000.css",
        "https://example.com/a.png": "/api/r0001.png",
    }
    out = rewrite_html(html, "https://example.com/", manifest)
    assert "script" not in out and "onload" not in out
    assert "/api/r0000.css" in out and "/api/r0001.png" in out
    assert mime_for_resource("r0000.css") == "text/css"
    assert mime_for_resource("r0001.weird") == "application/octet-stream"
