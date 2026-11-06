"""Produce snapshot outputs for one source asset in a single pass.

Every expensive intermediate is created at most once per job and shared by all requested
outputs: the source file (local path or one download), the office→PDF conversion, the link
page render (one Chromium page load for thumbnail, screenshot, page PDF, HTML archive and
readable text) and the text extraction. Files are written to the job's temporary work dir;
the worker uploads them and the work dir is removed afterwards.
"""

from __future__ import annotations

import asyncio
import html
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from app.core.config import Settings
from app.core.logging import get_logger
from app.modules.llm.client import AIUnavailableError
from app.modules.snapshots.browser import BrowserManager, PageCapture, RenderRequest
from app.modules.snapshots.egress import (
    BlockedDestinationError,
    EgressProxy,
    FetchError,
    fetch_html,
    parse_public_url,
)
from app.modules.snapshots.errors import SnapshotError
from app.modules.snapshots.extraction import ExtractionResult, extract_markdown
from app.modules.snapshots.extraction.ai import AIEnrichment
from app.modules.snapshots.extraction.files import decode_text
from app.modules.snapshots.extraction.media import MediaError, video_frame
from app.modules.snapshots.extraction.office import (
    OfficeConversionResult,
    convert_office_to_pdf,
    office_failure_message,
)
from app.modules.snapshots.imaging import (
    ImageError,
    image_thumbnail,
    pdf_first_page_thumbnail,
    text_pdf,
    text_thumbnail,
    viewport_thumbnail,
)
from app.modules.snapshots.planning import AssetFacts
from app.modules.snapshots.rewriter import rewrite_css, rewrite_html
from app.platform.storage.keys import file_suffix
from app.platform.storage.service import StorageBackend

logger = get_logger(__name__)

MAX_MARKDOWN_CHARS: Final = 1_000_000
THUMBNAIL_TEXT_CHARS: Final = 5000
TEXT_PREVIEW_MIME_TYPES: Final = frozenset(
    {"application/json", "text/csv", "text/html", "text/markdown", "text/plain", "text/uri-list"}
)
TEXT_PREVIEW_SUFFIXES: Final = frozenset(
    {".csv", ".html", ".htm", ".json", ".md", ".markdown", ".txt", ".url"}
)
PLAIN_TEXT_PDF_SUFFIXES: Final = frozenset({".csv", ".json", ".md", ".markdown", ".txt"})
AUDIO_PREVIEW_TEXT: Final = "Audio file\n\nSaved voice or audio attachment."
# Order matters only for sharing: text first so thumbnails/PDFs can reuse it.
PRODUCTION_ORDER: Final = (
    "markdown",
    "thumbnail_text",
    "thumbnail",
    "screenshot",
    "pdf",
    "webpage_html",
)


@dataclass(frozen=True, slots=True)
class SourceAsset:
    """Plain copy of the asset row: processing never holds ORM objects or a DB session."""

    id: str
    content_object_id: str
    media_type: str
    mime_type: str | None
    filename: str
    storage_key: str
    text_content: str | None

    @property
    def facts(self) -> AssetFacts:
        return AssetFacts(self.media_type, self.mime_type, self.filename)


@dataclass(slots=True)
class GeneratedArtifact:
    artifact_type: str
    filename: str
    mime_type: str
    path: Path | None = None  # file to upload
    text: str | None = None  # inline text artifact (no storage object)
    resources_dir: Path | None = None  # HTML archive static resources
    metadata: dict[str, Any] = field(default_factory=dict)


Outcome = GeneratedArtifact | SnapshotError


class SnapshotGenerator:
    def __init__(
        self,
        settings: Settings,
        storage: StorageBackend,
        browser: BrowserManager,
        egress: EgressProxy,
        ai: AIEnrichment,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.browser = browser
        self.egress = egress
        self.ai = ai

    async def generate(
        self,
        asset: SourceAsset,
        job_types: Iterable[str],
        work_dir: Path,
        *,
        artifact_ids: Mapping[str, str],
    ) -> dict[str, Outcome]:
        """One outcome per requested job type; never raises for a bad input."""
        requested = set(job_types)
        run = _Run(self, asset, requested, work_dir, artifact_ids)
        outcomes: dict[str, Outcome] = {}
        for job_type in sorted(requested, key=_production_rank):
            try:
                outcomes[job_type] = await run.produce(job_type)
            except SnapshotError as exc:
                outcomes[job_type] = exc
            except AIUnavailableError as exc:
                outcomes[job_type] = SnapshotError(
                    f"AI provider unavailable: {exc}", retryable=True
                )
            except Exception as exc:  # noqa: BLE001 - one bad input must not kill the worker
                logger.error(
                    "snapshot.generate.unexpected_error",
                    asset_id=asset.id,
                    job_type=job_type,
                    error=str(exc),
                    exc_info=True,
                )
                outcomes[job_type] = SnapshotError(
                    f"Unexpected error: {type(exc).__name__}: {exc}", retryable=True
                )
        return outcomes


def _production_rank(job_type: str) -> int:
    return PRODUCTION_ORDER.index(job_type) if job_type in PRODUCTION_ORDER else 99


class _Run:
    """Per-job lazily computed inputs (implements `ExtractionSource`)."""

    def __init__(
        self,
        generator: SnapshotGenerator,
        asset: SourceAsset,
        requested: set[str],
        work_dir: Path,
        artifact_ids: Mapping[str, str],
    ) -> None:
        self.generator = generator
        self.settings = generator.settings
        self.asset = asset
        self.facts = asset.facts
        self.text_content = asset.text_content
        self.requested = requested
        self.work_dir = work_dir
        self.artifact_ids = artifact_ids
        self._source: Path | None = None
        self._office: OfficeConversionResult | None = None
        self._capture: PageCapture | SnapshotError | None = None
        self._text: ExtractionResult | SnapshotError | None = None

    # --- shared inputs -------------------------------------------------------------------
    async def path(self) -> Path:
        if self._source is None:
            local = self.generator.storage.local_path(self.asset.storage_key)
            if local is not None and await asyncio.to_thread(local.is_file):
                self._source = local
            else:
                target = self.work_dir / f"source{file_suffix(self.asset.filename)}"
                await self.generator.storage.download_to(self.asset.storage_key, target)
                self._source = target
        return self._source

    async def office_pdf(self) -> Path:
        if self._office is None:
            self._office = await convert_office_to_pdf(
                await self.path(), self.work_dir, self.settings
            )
        if self._office.pdf_path is None:
            raise SnapshotError(
                office_failure_message(
                    asset_filename=self.asset.filename,
                    result=self._office,
                    timeout_seconds=self.settings.snapshot_office_converter_timeout_seconds,
                )
            )
        return self._office.pdf_path

    async def link_url(self) -> str:
        value = self.text_content
        if value is None:
            source = await self.path()
            value = decode_text(await asyncio.to_thread(_read_head, source, 64 * 1024))
        for line in (value or "").splitlines():
            candidate = line.strip()
            if candidate and not candidate.startswith("#"):
                try:
                    parse_public_url(candidate)
                except BlockedDestinationError as exc:
                    raise SnapshotError(str(exc)) from exc
                return candidate
        raise SnapshotError("Link does not contain a URL.")

    async def capture(self) -> PageCapture:
        if self._capture is None:
            wants = self.requested
            request = RenderRequest(
                url=await self.link_url(),
                out_dir=self.work_dir,
                html="markdown" in wants or "thumbnail_text" in wants,
                screenshot="thumbnail" in wants,
                full_page="screenshot" in wants,
                pdf="pdf" in wants,
                archive="webpage_html" in wants,
            )
            try:
                self._capture = await self.generator.browser.render(request)
            except SnapshotError as exc:
                logger.info("snapshot.link.render_failed", url=request.url, error=str(exc))
                self._capture = exc
        if isinstance(self._capture, SnapshotError):
            raise self._capture
        return self._capture

    async def page_html(self) -> tuple[str, str]:
        try:
            capture = await self.capture()
            if capture.html is not None:
                return capture.url, capture.html
        except SnapshotError as exc:
            if not exc.retryable:  # blocked/invalid URL: a plain fetch is refused as well
                raise
        try:
            return await fetch_html(await self.link_url(), self.generator.egress)
        except BlockedDestinationError as exc:
            raise SnapshotError(str(exc)) from exc
        except FetchError as exc:
            raise SnapshotError(str(exc), retryable=exc.retryable) from exc

    async def text(self) -> ExtractionResult:
        if self._text is None:
            try:
                self._text = await extract_markdown(self, self.settings, self.generator.ai)
            except SnapshotError as exc:
                self._text = exc
        if isinstance(self._text, SnapshotError):
            raise self._text
        return self._text

    def _is_text_like(self) -> bool:
        facts = self.facts
        return (
            facts.media_type in {"text", "link"}
            or (facts.mime_type or "") in TEXT_PREVIEW_MIME_TYPES
            or facts.suffix in TEXT_PREVIEW_SUFFIXES
        )

    def _out(self, name: str) -> Path:
        return self.work_dir / name

    # --- outputs -------------------------------------------------------------------------
    async def produce(self, job_type: str) -> GeneratedArtifact:
        match job_type:
            case "markdown":
                return await self._markdown()
            case "thumbnail_text":
                return await self._thumbnail_text()
            case "thumbnail":
                return await self._thumbnail()
            case "screenshot":
                return await self._screenshot()
            case "pdf":
                return await self._pdf()
            case "webpage_html":
                return await self._webpage_html()
        raise SnapshotError(f"Unsupported snapshot job type: {job_type}")

    async def _markdown(self) -> GeneratedArtifact:
        result = await self.text()
        body = result.markdown.strip()[:MAX_MARKDOWN_CHARS]
        path = self._out("snapshot.md")
        await asyncio.to_thread(
            path.write_text, f"# {self.asset.filename}\n\n{body}\n", encoding="utf-8"
        )
        return GeneratedArtifact(
            "markdown", "snapshot.md", "text/markdown", path=path,
            metadata={"extraction": result.metadata_dict()},
        )  # fmt: skip

    async def _thumbnail_text(self) -> GeneratedArtifact:
        result = await self.text()
        return GeneratedArtifact(
            "thumbnail_text", "thumbnail.txt", "text/plain",
            text=result.markdown[:THUMBNAIL_TEXT_CHARS],
        )  # fmt: skip

    async def _thumbnail(self, artifact_type: str = "thumbnail") -> GeneratedArtifact:
        out = self._out(f"{artifact_type}.webp")
        facts = self.facts
        try:
            if facts.is_link:
                capture = await self.capture()
                if capture.screenshot is None:
                    raise SnapshotError("Page screenshot was not captured.", retryable=True)
                await asyncio.to_thread(
                    viewport_thumbnail, capture.screenshot, out, viewport=(1280, 800)
                )
            elif facts.media_type == "image":
                await asyncio.to_thread(image_thumbnail, await self.path(), out)
            elif facts.media_type == "audio":
                await asyncio.to_thread(
                    text_thumbnail, self.asset.filename, AUDIO_PREVIEW_TEXT, out
                )
            elif facts.media_type == "video":
                frame = await video_frame(
                    await self.path(), self._out("video-frame.jpg"),
                    timeout=float(self.settings.snapshot_timeout_seconds),
                )  # fmt: skip
                await asyncio.to_thread(image_thumbnail, frame, out)
            elif facts.is_pdf:
                await asyncio.to_thread(pdf_first_page_thumbnail, await self.path(), out)
            elif self._is_text_like():
                preview = (await self.text()).plain_text
                await asyncio.to_thread(text_thumbnail, self.asset.filename, preview, out)
            else:
                await asyncio.to_thread(pdf_first_page_thumbnail, await self.office_pdf(), out)
        except (ImageError, MediaError) as exc:
            raise SnapshotError(str(exc)) from exc
        return GeneratedArtifact(artifact_type, out.name, "image/webp", path=out)

    async def _screenshot(self) -> GeneratedArtifact:
        if self.facts.is_link:
            capture = await self.capture()
            if capture.screenshot is None:
                raise SnapshotError("Page screenshot was not captured.", retryable=True)
            return GeneratedArtifact(
                "screenshot", "screenshot.jpg", "image/jpeg", path=capture.screenshot
            )
        if self.facts.media_type == "image":
            source = await self.path()
            return GeneratedArtifact(
                "screenshot",
                f"screenshot{file_suffix(self.asset.filename)}",
                self.asset.mime_type or "application/octet-stream",
                path=source,
            )
        return await self._thumbnail("screenshot")

    async def _pdf(self) -> GeneratedArtifact:
        facts = self.facts
        if facts.is_link:
            capture = await self.capture()
            if capture.pdf is None:
                raise SnapshotError("Page PDF was not captured.", retryable=True)
            return GeneratedArtifact("pdf", "snapshot.pdf", "application/pdf", path=capture.pdf)
        if facts.is_pdf:
            return GeneratedArtifact(
                "pdf", "snapshot.pdf", "application/pdf", path=await self.path()
            )
        plain = (
            self.text_content is not None
            or facts.suffix in PLAIN_TEXT_PDF_SUFFIXES
            or (facts.media_type == "text")
        )
        if not plain:
            try:
                return GeneratedArtifact(
                    "pdf", "snapshot.pdf", "application/pdf", path=await self.office_pdf()
                )
            except SnapshotError:
                if not self._is_text_like():
                    raise
        out = self._out("snapshot.pdf")
        await asyncio.to_thread(
            text_pdf, self.asset.filename, (await self.text()).plain_text, out,
            max_pages=self.settings.snapshot_max_pdf_pages,
        )  # fmt: skip
        return GeneratedArtifact("pdf", "snapshot.pdf", "application/pdf", path=out)

    async def _webpage_html(self) -> GeneratedArtifact:
        out = self._out("snapshot.html")
        facts = self.facts
        if facts.is_link:
            capture = await self.capture()
            if capture.html is None:
                raise SnapshotError("Page HTML was not captured.", retryable=True)
            artifact_id = self.artifact_ids["webpage_html"]
            resources_dir = self.work_dir / "resources"
            await asyncio.to_thread(
                _write_archive, capture, out, resources_dir, artifact_id,
                self.settings.api_prefix,
            )  # fmt: skip
            return GeneratedArtifact(
                "webpage_html", "snapshot.html", "text/html", path=out,
                resources_dir=resources_dir if capture.resources else None,
            )  # fmt: skip
        if facts.mime_type == "text/html" or facts.suffix in {".html", ".htm"}:
            source = await self.path()
            await asyncio.to_thread(shutil.copyfile, source, out)
        else:
            text = (await self.text()).plain_text
            await asyncio.to_thread(
                out.write_text,
                '<!doctype html><html><head><meta charset="utf-8">'
                f"<title>{html.escape(self.asset.filename)}</title></head><body><pre>"
                f"{html.escape(text)}</pre></body></html>",
                encoding="utf-8",
            )
        return GeneratedArtifact("webpage_html", "snapshot.html", "text/html", path=out)


def _write_archive(
    capture: PageCapture, out: Path, resources_dir: Path, artifact_id: str, api_prefix: str
) -> None:
    """Rewrite the page and its CSS to point at the archived copies; scripts are removed."""
    base = f"{api_prefix}/snapshots/artifacts/{artifact_id}/resources/"
    manifest = {item.original_url: base + item.filename for item in capture.resources}
    for item in capture.resources:
        if item.content_type == "text/css":
            path = resources_dir / item.filename
            css = path.read_bytes().decode("utf-8", errors="replace")
            path.write_text(rewrite_css(css, item.original_url, manifest), encoding="utf-8")
    out.write_text(rewrite_html(capture.html or "", capture.url, manifest), encoding="utf-8")


def _read_head(path: Path, size: int) -> bytes:
    with path.open("rb") as handle:
        return handle.read(size)
