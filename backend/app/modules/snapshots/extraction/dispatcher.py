from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.modules.content.models import ContentAsset
from app.modules.snapshots.extraction.core import ExtractionResult, ExtractorContext
from app.modules.snapshots.extraction.office import office_failure_message
from app.modules.snapshots.extraction.files import (
    extract_csv,
    extract_docx,
    extract_html_file,
    extract_image,
    extract_json,
    extract_markdown_file,
    extract_media,
    extract_pdf,
    extract_plain_text,
)
from app.modules.snapshots.extraction.html import html_to_markdown
from app.modules.snapshots.extraction.providers import (
    build_ocr_provider,
    build_stt_provider,
    build_vision_provider,
)


def extract_asset_text(
    *,
    asset: ContentAsset,
    source_path: Path,
    context: ExtractorContext,
    render_page_image: Callable[[Any, int], Path],
) -> ExtractionResult | None:
    if asset.media_type == "link":
        url = context.link_url(asset, source_path)
        html = context.fetch_webpage_html(url)
        return html_to_markdown(html, source_url=url, source_kind="webpage")
    if asset.text_content:
        return extract_markdown_file(asset.text_content)

    suffix = Path(asset.filename).suffix.lower()
    mime_type = asset.mime_type or ""
    if asset.media_type == "text" or suffix in {".txt", ".md", ".markdown", ".csv", ".json"}:
        text = _decode_text(source_path)
        if text is None:
            return None
        if mime_type == "text/markdown" or suffix in {".md", ".markdown"}:
            return extract_markdown_file(text)
        if mime_type == "text/csv" or suffix == ".csv":
            return extract_csv(text)
        if mime_type == "application/json" or suffix == ".json":
            return extract_json(text)
        return extract_plain_text(text)
    if mime_type == "text/html" or suffix in {".html", ".htm"}:
        text = _decode_text(source_path)
        return extract_html_file(text) if text is not None else None
    if mime_type == "application/pdf" or suffix == ".pdf":
        return extract_pdf(
            source_path,
            ocr_provider=build_ocr_provider(),
            render_page_image=render_page_image,
            max_pages=get_settings().snapshot_extraction_max_pdf_pages,
        )
    if suffix == ".docx":
        return extract_docx(source_path)
    if asset.media_type == "image":
        return extract_image(
            source_path,
            ocr_provider=build_ocr_provider(),
            vision_provider=build_vision_provider(),
        )
    if asset.media_type in {"audio", "video"}:
        return extract_media(
            source_path,
            stt_provider=build_stt_provider(),
            vision_provider=build_vision_provider(),
            source_kind=asset.media_type,
            max_description_seconds=get_settings().snapshot_vision_max_video_seconds,
        )

    office_result = context.convert_office_to_pdf(source_path)
    if office_result.ok and office_result.pdf_path is not None:
        return extract_pdf(
            office_result.pdf_path,
            ocr_provider=build_ocr_provider(),
            render_page_image=render_page_image,
            max_pages=get_settings().snapshot_extraction_max_pdf_pages,
        )
    if office_result.failure_kind is not None:
        # Imported lazily to avoid a circular import between artifacts and
        # extraction modules.
        from app.modules.snapshots.artifacts import UnsupportedSnapshotError

        raise UnsupportedSnapshotError(
            office_failure_message(
                asset_filename=asset.filename,
                result=office_result,
                timeout_seconds=get_settings().snapshot_office_converter_timeout_seconds,
            )
        )
    return None


def _decode_text(source_path: Path) -> str | None:
    data = source_path.read_bytes()
    for encoding in ("utf-8", "utf-16", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None
