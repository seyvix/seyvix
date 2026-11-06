"""Text (markdown) extraction for one source asset. CPU work runs in worker threads."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Final, Protocol

from app.core.config import Settings
from app.core.logging import get_logger
from app.modules.llm.client import AIResponseError, AIUnavailableError
from app.modules.snapshots.errors import SnapshotError
from app.modules.snapshots.extraction.ai import AIEnrichment
from app.modules.snapshots.extraction.core import (
    ExtractionResult,
    normalize_blank_lines,
    plain_text_from_markdown,
)
from app.modules.snapshots.extraction.files import (
    PdfPageText,
    build_pdf_result,
    decode_text,
    extract_csv,
    extract_docx,
    extract_html_file,
    extract_json,
    extract_markdown_file,
    extract_plain_text,
    read_pdf_text,
)
from app.modules.snapshots.extraction.html import html_to_markdown
from app.modules.snapshots.extraction.media import MediaError, audio_chunks, video_frames
from app.modules.snapshots.imaging import ImageError, image_for_ai, render_pdf_page_jpeg
from app.modules.snapshots.planning import AssetFacts

logger = get_logger(__name__)

MAX_TEXT_FILE_BYTES: Final = 5 * 1024 * 1024
OCR_CONCURRENCY: Final = 3
TEXT_SUFFIXES: Final = frozenset({".txt", ".md", ".markdown", ".csv", ".json"})


class ExtractionSource(Protocol):
    """Lazily materialized inputs of one asset (each produced at most once per job)."""

    facts: AssetFacts
    text_content: str | None
    work_dir: Path

    async def path(self) -> Path: ...

    async def office_pdf(self) -> Path: ...

    async def page_html(self) -> tuple[str, str]: ...


async def extract_markdown(
    source: ExtractionSource, settings: Settings, ai: AIEnrichment
) -> ExtractionResult:
    try:
        result = await _extract(source, settings, ai)
    except AIUnavailableError as exc:
        raise SnapshotError(f"AI provider unavailable: {exc}", retryable=True) from exc
    if result is None or not result.markdown.strip():
        reason = "; ".join(result.warnings) if result is not None else ""
        raise SnapshotError(reason or "No text could be extracted from this file.")
    return result


async def _extract(
    source: ExtractionSource, settings: Settings, ai: AIEnrichment
) -> ExtractionResult | None:
    facts = source.facts
    if facts.is_link:
        url, html = await source.page_html()
        return await asyncio.to_thread(
            html_to_markdown, html, source_url=url, source_kind="webpage"
        )
    if source.text_content:
        return await asyncio.to_thread(extract_markdown_file, source.text_content)

    mime_type = facts.mime_type or ""
    if facts.media_type == "text" or facts.suffix in TEXT_SUFFIXES:
        text = await _read_text(await source.path())
        if text is None:
            return None
        if mime_type == "text/markdown" or facts.suffix in {".md", ".markdown"}:
            return await asyncio.to_thread(extract_markdown_file, text)
        if mime_type == "text/csv" or facts.suffix == ".csv":
            return await asyncio.to_thread(extract_csv, text)
        if mime_type == "application/json" or facts.suffix == ".json":
            return await asyncio.to_thread(extract_json, text)
        return await asyncio.to_thread(extract_plain_text, text)
    if mime_type == "text/html" or facts.suffix in {".html", ".htm"}:
        text = await _read_text(await source.path())
        return await asyncio.to_thread(extract_html_file, text) if text is not None else None
    if facts.is_pdf:
        return await extract_pdf(await source.path(), settings, ai)
    if facts.suffix == ".docx":
        docx = await asyncio.to_thread(extract_docx, await source.path())
        if docx is not None:
            return docx
    if facts.media_type == "image":
        return await extract_image(await source.path(), facts.mime_type, settings, ai)
    if facts.media_type in {"audio", "video"}:
        return await extract_media(await source.path(), facts.media_type, source, settings, ai)
    return await extract_pdf(await source.office_pdf(), settings, ai)


async def _read_text(path: Path) -> str | None:
    def read() -> str | None:
        with path.open("rb") as handle:
            return decode_text(handle.read(MAX_TEXT_FILE_BYTES))

    return await asyncio.to_thread(read)


async def extract_pdf(path: Path, settings: Settings, ai: AIEnrichment) -> ExtractionResult | None:
    try:
        pages, total = await asyncio.to_thread(
            read_pdf_text, path, max_pages=settings.snapshot_max_pdf_pages
        )
    except RuntimeError as exc:  # MuPDF: broken/encrypted document
        raise SnapshotError(f"PDF cannot be read: {exc}") from exc
    ocr_texts: dict[int, str] = {}
    ocr_warnings: dict[int, str] = {}
    candidates = [page for page in pages if page.needs_ocr]
    if candidates and ai.ocr_enabled:
        limiter = asyncio.Semaphore(OCR_CONCURRENCY)

        async def ocr_page(page: PdfPageText) -> None:
            async with limiter:
                image = await asyncio.to_thread(render_pdf_page_jpeg, path, page.number - 1)
                try:
                    ocr_texts[page.number] = await ai.ocr(image, "image/jpeg")
                except AIResponseError as exc:
                    ocr_warnings[page.number] = f"OCR failed: {exc}"

        try:
            async with asyncio.TaskGroup() as group:
                for page in candidates:
                    group.create_task(ocr_page(page))
        except* AIUnavailableError as errors:
            raise errors.exceptions[0] from None
    elif candidates:
        for page in candidates:
            ocr_warnings[page.number] = "ocr_disabled"
    return await asyncio.to_thread(
        build_pdf_result,
        pages,
        total_pages=total,
        ocr_texts=ocr_texts,
        ocr_warnings=ocr_warnings,
    )


async def extract_image(
    path: Path, mime_type: str | None, settings: Settings, ai: AIEnrichment
) -> ExtractionResult | None:
    if not (ai.ocr_enabled or ai.vision_enabled):
        return None
    try:
        image, image_mime = await asyncio.to_thread(
            image_for_ai, path, mime_type, max_bytes=settings.snapshot_max_image_bytes
        )
    except ImageError as exc:
        raise SnapshotError(str(exc)) from exc
    blocks: list[str] = []
    methods: list[str] = []
    warnings: list[str] = []
    if ai.vision_enabled:
        try:
            if description := normalize_blank_lines(await ai.describe_image(image, image_mime)):
                blocks.append(f"## Image description\n\n{description}")
                methods.append("vision")
        except AIResponseError as exc:
            warnings.append(f"Image description failed: {exc}")
    if ai.ocr_enabled:
        try:
            if text := normalize_blank_lines(await ai.ocr(image, image_mime)):
                blocks.append(f"## OCR text\n\n{text}")
                methods.append("ocr")
        except AIResponseError as exc:
            warnings.append(f"OCR failed: {exc}")
    return _assemble(blocks, methods, warnings, source_kind="image")


async def extract_media(
    path: Path, kind: str, source: ExtractionSource, settings: Settings, ai: AIEnrichment
) -> ExtractionResult | None:
    blocks: list[str] = []
    methods: list[str] = []
    warnings: list[str] = []
    timeout = float(settings.snapshot_timeout_seconds)
    if kind == "video" and ai.vision_enabled:
        description = await _describe_video(
            path, source.work_dir / "frames", settings, ai, warnings, timeout
        )
        if description:
            blocks.append(f"## Video description\n\n{description}")
            methods.append("vision")
    if ai.transcription_enabled:
        try:
            chunks = await audio_chunks(
                path,
                source.work_dir / "audio",
                max_seconds=settings.snapshot_max_media_seconds,
                chunk_seconds=settings.snapshot_transcription_chunk_seconds,
                timeout=timeout,
            )
        except MediaError as exc:
            warnings.append(f"Audio extraction failed: {exc}")
            chunks = []
        transcripts: list[str] = []
        for chunk in chunks:
            try:
                if text := (await ai.transcribe(chunk)).strip():
                    transcripts.append(text)
            except AIResponseError as exc:
                warnings.append(f"Transcription failed: {exc}")
            finally:
                chunk.unlink(missing_ok=True)
        if transcripts:
            blocks.append("## Transcript\n\n" + "\n\n".join(transcripts))
            methods.append("stt")
    return _assemble(blocks, methods, warnings, source_kind=kind)


async def _describe_video(
    path: Path,
    frames_dir: Path,
    settings: Settings,
    ai: AIEnrichment,
    warnings: list[str],
    timeout: float,
) -> str:
    interval = max(settings.snapshot_vision_video_frame_interval_seconds, 1)
    try:
        frames = await video_frames(
            path,
            frames_dir,
            max_seconds=min(
                settings.snapshot_vision_max_video_seconds, settings.snapshot_max_media_seconds
            ),
            interval_seconds=interval,
            timeout=timeout,
        )
    except MediaError as exc:
        warnings.append(f"Video frame extraction failed: {exc}")
        return ""
    per_request = max(settings.snapshot_vision_max_frames_per_request, 1)
    descriptions: list[str] = []
    for index in range(0, len(frames), per_request):
        batch = frames[index : index + per_request]
        start, end = index * interval, (index + len(batch)) * interval
        images = await asyncio.to_thread(_read_files, batch)
        try:
            if text := normalize_blank_lines(
                await ai.describe_frames(images, start=start, end=end)
            ):
                descriptions.append(f"Segment {start}-{end}s: {text}")
        except AIResponseError as exc:
            warnings.append(f"Video description failed: {exc}")
    return "\n\n".join(descriptions)


def _read_files(paths: list[Path]) -> list[bytes]:
    return [path.read_bytes() for path in paths]


def _assemble(
    blocks: list[str], methods: list[str], warnings: list[str], *, source_kind: str
) -> ExtractionResult | None:
    markdown = normalize_blank_lines("\n\n".join(blocks))
    if not markdown:
        if warnings:
            return ExtractionResult(
                markdown="", plain_text="", source_kind=source_kind, method="ai",
                warnings=warnings, quality=0.0,
            )  # fmt: skip
        return None
    return ExtractionResult(
        markdown=markdown,
        plain_text=plain_text_from_markdown(markdown),
        source_kind=source_kind,
        method="+".join(methods),
        warnings=warnings,
        quality=None,
    )
