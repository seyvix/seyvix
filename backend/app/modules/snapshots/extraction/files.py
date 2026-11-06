from __future__ import annotations

import csv
import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

import fitz  # type: ignore[import-untyped]

from app.modules.snapshots.extraction.core import (
    ExtractionPage,
    ExtractionResult,
    normalize_blank_lines,
    plain_text_from_markdown,
)
from app.modules.snapshots.extraction.html import html_to_markdown


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


def extract_html_file(value: str) -> ExtractionResult:
    return html_to_markdown(value, source_kind="html")


OCR_REPLACE_QUALITY = 0.2
OCR_COMPARE_QUALITY = 0.5


@dataclass(frozen=True, slots=True)
class PdfPageText:
    number: int
    text: str
    quality: float

    @property
    def needs_ocr(self) -> bool:
        return self.quality < OCR_COMPARE_QUALITY


def read_pdf_text(source_path: Path, *, max_pages: int) -> tuple[list[PdfPageText], int]:
    """Embedded text of the first `max_pages` pages plus the total page count."""
    with fitz.open(str(source_path)) as doc:
        pages = [
            PdfPageText(index + 1, text, _text_quality(text))
            for index in range(min(doc.page_count, max_pages))
            for text in [normalize_blank_lines(doc[index].get_text("text"))]
        ]
        return pages, doc.page_count


def build_pdf_result(
    pages: list[PdfPageText],
    *,
    total_pages: int,
    ocr_texts: dict[int, str],
    ocr_warnings: dict[int, str],
) -> ExtractionResult | None:
    """Choose embedded text or OCR text per page and assemble the document markdown."""
    warnings: list[str] = []
    if total_pages > len(pages):
        warnings.append(f"PDF extraction stopped after {len(pages)} pages.")
    page_records: list[ExtractionPage] = []
    page_markdown: list[str] = []
    for page in pages:
        selected, method, quality = page.text, "pdf-text", page.quality
        page_warnings: list[str] = []
        ocr_text = normalize_blank_lines(ocr_texts.get(page.number, ""))
        if page.number in ocr_warnings:
            page_warnings.append(ocr_warnings[page.number])
        if page.quality < OCR_REPLACE_QUALITY:
            if ocr_text:
                selected, method, quality = ocr_text, "ocr", _text_quality(ocr_text)
            elif not page_warnings:
                page_warnings.append("ocr_unavailable")
        elif page.needs_ocr and ocr_text and _text_distance_hint(page.text, ocr_text) > 0.45:
            page_warnings.append("pdf_text_ocr_mismatch")
            warnings.append(f"Page {page.number}: embedded PDF text differs from OCR text.")
            if _text_quality(ocr_text) > quality:
                selected, method, quality = ocr_text, "ocr", _text_quality(ocr_text)
        if selected:
            page_markdown.append(f"## Page {page.number}\n\n{selected}")
        page_records.append(
            ExtractionPage(
                page_number=page.number,
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
        pages=page_records,
        quality=_text_quality(markdown),
    )


def decode_text(data: bytes) -> str | None:
    for encoding in ("utf-8", "utf-16", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _escape_table_cell(value: str) -> str:
    return value.strip().replace("|", "\\|")


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
