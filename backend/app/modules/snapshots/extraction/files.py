from __future__ import annotations

import csv
import io
import json
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from app.modules.snapshots.extraction.core import (
    ExtractionPage,
    ExtractionResult,
    normalize_blank_lines,
    plain_text_from_markdown,
)
from app.modules.snapshots.extraction.html import html_to_markdown
from app.modules.snapshots.extraction.providers import OcrProvider, SttProvider, VisionProvider


def extract_plain_text(value: str, *, source_kind: str = "text") -> ExtractionResult:
    markdown = normalize_blank_lines(value)
    return ExtractionResult(
        markdown=markdown,
        plain_text=markdown,
        source_kind=source_kind,
        method="text",
        quality=_text_quality(markdown),
    )


def extract_markdown_file(value: str) -> ExtractionResult:
    markdown = normalize_blank_lines(value)
    return ExtractionResult(
        markdown=markdown,
        plain_text=plain_text_from_markdown(markdown),
        source_kind="markdown",
        method="markdown",
        quality=_text_quality(markdown),
    )


def extract_json(value: str) -> ExtractionResult:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return extract_plain_text(value, source_kind="json")
    markdown = "```json\n" + json.dumps(parsed, ensure_ascii=False, indent=2) + "\n```"
    return ExtractionResult(
        markdown=markdown,
        plain_text=json.dumps(parsed, ensure_ascii=False),
        source_kind="json",
        method="json",
        quality=_text_quality(markdown),
    )


def extract_csv(value: str) -> ExtractionResult:
    reader = csv.reader(io.StringIO(value))
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        return extract_plain_text(value, source_kind="csv")
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    lines = [
        "| " + " | ".join(_escape_table_cell(cell) for cell in padded[0]) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    for row in padded[1:]:
        lines.append("| " + " | ".join(_escape_table_cell(cell) for cell in row) + " |")
    markdown = "\n".join(lines)
    return ExtractionResult(
        markdown=markdown,
        plain_text=plain_text_from_markdown(markdown),
        source_kind="csv",
        method="csv",
        quality=_text_quality(markdown),
    )


def extract_docx(source_path: Path) -> ExtractionResult | None:
    try:
        with zipfile.ZipFile(source_path) as archive:
            xml = archive.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile):
        return None

    root = ElementTree.fromstring(xml)
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    body = root.find(f"{namespace}body")
    if body is None:
        return None
    blocks: list[str] = []
    for child in body:
        if child.tag == f"{namespace}p":
            text = _docx_paragraph_text(child, namespace)
            if text:
                blocks.append(text)
        elif child.tag == f"{namespace}tbl":
            table = _docx_table_markdown(child, namespace)
            if table:
                blocks.append(table)
    markdown = normalize_blank_lines("\n\n".join(blocks))
    if not markdown:
        return None
    return ExtractionResult(
        markdown=markdown,
        plain_text=plain_text_from_markdown(markdown),
        source_kind="docx",
        method="docx-xml",
        quality=_text_quality(markdown),
    )


def _docx_paragraph_text(paragraph: ElementTree.Element, namespace: str) -> str:
    parts = [node.text or "" for node in paragraph.iter(f"{namespace}t")]
    return normalize_blank_lines("".join(parts))


def _docx_table_markdown(table: ElementTree.Element, namespace: str) -> str:
    rows: list[list[str]] = []
    for table_row in table.findall(f"{namespace}tr"):
        cells: list[str] = []
        for cell in table_row.findall(f"{namespace}tc"):
            paragraphs = [
                _docx_paragraph_text(paragraph, namespace)
                for paragraph in cell.findall(f"{namespace}p")
            ]
            cells.append(" ".join(paragraph for paragraph in paragraphs if paragraph).strip())
        if any(cells):
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    lines = [
        "| " + " | ".join(_escape_table_cell(cell) for cell in padded[0]) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    for markdown_row in padded[1:]:
        lines.append("| " + " | ".join(_escape_table_cell(cell) for cell in markdown_row) + " |")
    return "\n".join(lines)


def extract_pdf(
    source_path: Path,
    *,
    ocr_provider: OcrProvider,
    render_page_image: Callable[[Any, int], Path],
    max_pages: int,
) -> ExtractionResult | None:
    try:
        import fitz  # type: ignore[import-untyped]
    except ImportError:
        return None

    doc = fitz.open(str(source_path))
    try:
        pages: list[ExtractionPage] = []
        page_markdown: list[str] = []
        warnings: list[str] = []
        for index, page in enumerate(doc, start=1):
            if index > max_pages:
                warnings.append(f"PDF extraction stopped after {max_pages} pages.")
                break
            embedded = normalize_blank_lines(page.get_text("text"))
            method = "pdf-text"
            selected = embedded
            page_warnings: list[str] = []
            quality = _text_quality(embedded)

            if quality < 0.2:
                image_path = render_page_image(page, index)
                try:
                    ocr_text, ocr_warning = _safe_ocr_text(ocr_provider, image_path)
                finally:
                    image_path.unlink(missing_ok=True)
                if ocr_text:
                    selected = ocr_text
                    method = "ocr"
                    quality = _text_quality(ocr_text)
                else:
                    page_warnings.append(ocr_warning or "ocr_unavailable")
            elif quality < 0.5:
                image_path = render_page_image(page, index)
                try:
                    ocr_text, ocr_warning = _safe_ocr_text(ocr_provider, image_path)
                finally:
                    image_path.unlink(missing_ok=True)
                if ocr_warning:
                    page_warnings.append(ocr_warning)
                if ocr_text and _text_distance_hint(embedded, ocr_text) > 0.45:
                    page_warnings.append("pdf_text_ocr_mismatch")
                    warnings.append(f"Page {index}: embedded PDF text differs from OCR text.")
                    if _text_quality(ocr_text) > quality:
                        selected = ocr_text
                        method = "ocr"
                        quality = _text_quality(ocr_text)

            if selected:
                page_markdown.append(f"## Page {index}\n\n{selected}")
            pages.append(
                ExtractionPage(
                    page_number=index,
                    method=method,
                    char_count=len(selected),
                    quality=quality,
                    warnings=page_warnings,
                )
            )
        markdown = normalize_blank_lines("\n\n".join(page_markdown))
        if not markdown:
            return None
        return ExtractionResult(
            markdown=markdown,
            plain_text=plain_text_from_markdown(markdown),
            source_kind="pdf",
            method="pdf",
            warnings=warnings,
            pages=pages,
            quality=_text_quality(markdown),
        )
    finally:
        doc.close()


def extract_image(
    source_path: Path, *, ocr_provider: OcrProvider, vision_provider: VisionProvider
) -> ExtractionResult:
    ocr_text, ocr_warning = _safe_ocr_text(ocr_provider, source_path)
    description, description_warning = _safe_image_description(vision_provider, source_path)
    blocks: list[str] = []
    warnings = [warning for warning in (ocr_warning, description_warning) if warning is not None]
    methods: list[str] = []

    if description:
        blocks.append(f"## Image description\n\n{description}")
        methods.append("vision")
    if ocr_text:
        blocks.append(f"## OCR text\n\n{ocr_text}")
        methods.append("ocr")

    markdown = normalize_blank_lines("\n\n".join(blocks))
    if not markdown:
        return ExtractionResult(
            markdown="",
            plain_text="",
            source_kind="image",
            method="vision+ocr",
            warnings=warnings or ["Vision/OCR providers are disabled or returned no text."],
            quality=0.0,
        )
    return ExtractionResult(
        markdown=markdown,
        plain_text=plain_text_from_markdown(markdown),
        source_kind="image",
        method="+".join(methods),
        warnings=warnings,
        quality=_text_quality(markdown),
    )


def extract_media(
    source_path: Path,
    *,
    stt_provider: SttProvider,
    vision_provider: VisionProvider,
    source_kind: str,
    max_description_seconds: int,
) -> ExtractionResult:
    transcript, stt_warning = _safe_stt_text(stt_provider, source_path)
    description = ""
    description_warning: str | None = None
    if source_kind == "video":
        description, description_warning = _safe_video_description(
            vision_provider,
            source_path,
            max_seconds=max_description_seconds,
        )
    blocks: list[str] = []
    warnings = [warning for warning in (stt_warning, description_warning) if warning is not None]
    methods: list[str] = []

    if description:
        blocks.append(f"## Video description\n\n{description}")
        methods.append("vision")
    if transcript:
        blocks.append(f"## Transcript\n\n{transcript}")
        methods.append("stt")

    markdown = normalize_blank_lines("\n\n".join(blocks))
    if not markdown:
        return ExtractionResult(
            markdown="",
            plain_text="",
            source_kind=source_kind,
            method="vision+stt" if source_kind == "video" else "stt",
            warnings=warnings
            or [
                (
                    "Vision/speech-to-text providers are disabled or returned no text."
                    if source_kind == "video"
                    else "Speech-to-text provider is disabled or returned no text."
                )
            ],
            quality=0.0,
        )
    return ExtractionResult(
        markdown=markdown,
        plain_text=plain_text_from_markdown(markdown),
        source_kind=source_kind,
        method="+".join(methods),
        warnings=warnings,
        quality=_text_quality(markdown),
    )


def extract_html_file(value: str) -> ExtractionResult:
    return html_to_markdown(value, source_kind="html")


def _escape_table_cell(value: str) -> str:
    return value.strip().replace("|", "\\|")


def _safe_ocr_text(provider: OcrProvider, image_path: Path) -> tuple[str, str | None]:
    try:
        return normalize_blank_lines(provider.extract_image_text(image_path) or ""), None
    except Exception as exc:  # noqa: BLE001
        return "", f"OCR provider failed: {exc}"


def _safe_stt_text(provider: SttProvider, media_path: Path) -> tuple[str, str | None]:
    try:
        return normalize_blank_lines(provider.transcribe_media(media_path) or ""), None
    except Exception as exc:  # noqa: BLE001
        return "", f"Speech-to-text provider failed: {exc}"


def _safe_image_description(provider: VisionProvider, image_path: Path) -> tuple[str, str | None]:
    try:
        return normalize_blank_lines(provider.describe_image(image_path) or ""), None
    except Exception as exc:  # noqa: BLE001
        return "", f"Vision description provider failed: {exc}"


def _safe_video_description(
    provider: VisionProvider, video_path: Path, *, max_seconds: int
) -> tuple[str, str | None]:
    try:
        return (
            normalize_blank_lines(
                provider.describe_video(video_path, max_seconds=max_seconds) or ""
            ),
            None,
        )
    except Exception as exc:  # noqa: BLE001
        return "", f"Vision description provider failed: {exc}"


def _text_quality(value: str) -> float:
    stripped = value.strip()
    if not stripped:
        return 0.0
    words = len(stripped.split())
    alpha = sum(1 for char in stripped if char.isalpha())
    ratio = alpha / max(len(stripped), 1)
    return min(1.0, (words / 80) * 0.7 + ratio * 0.3)


def _text_distance_hint(left: str, right: str) -> float:
    left_words = set(left.casefold().split())
    right_words = set(right.casefold().split())
    if not left_words and not right_words:
        return 0.0
    overlap = len(left_words & right_words)
    total = len(left_words | right_words)
    return 1 - overlap / max(total, 1)
