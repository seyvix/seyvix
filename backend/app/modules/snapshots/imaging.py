"""CPU-bound image/PDF helpers. All functions are synchronous: call via `asyncio.to_thread`."""

from __future__ import annotations

import io
import textwrap
from functools import cache
from pathlib import Path
from typing import Any, Final

import fitz  # type: ignore[import-untyped]
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

THUMBNAIL_MAX_SIZE: Final = (512, 512)
THUMBNAIL_QUALITY: Final = 80
TEXT_THUMBNAIL_SIZE: Final = (362, 512)  # A4 portrait
AI_IMAGE_MAX_SIDE: Final = 2048
AI_IMAGE_MIME_TYPES: Final = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})
# Pillow refuses images above this (decompression-bomb guard, ~16k x 16k).
Image.MAX_IMAGE_PIXELS = 256_000_000

_SANS_FONTS: Final = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
)
_MONO_FONTS: Final = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    *_SANS_FONTS,
)


class ImageError(Exception):
    """The input cannot be rendered."""


@cache
def _font_path(mono: bool) -> str | None:
    """A TTF with Cyrillic coverage (the snapshot image installs DejaVu)."""
    return next(
        (path for path in (_MONO_FONTS if mono else _SANS_FONTS) if Path(path).is_file()), None
    )


def _font(size: int, *, mono: bool) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = _font_path(mono)
    if path is None:
        return ImageFont.load_default(size)
    return ImageFont.truetype(path, size)


def _save_webp(image: Image.Image, out_path: Path) -> tuple[int, int]:
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    image.thumbnail(THUMBNAIL_MAX_SIZE, Image.Resampling.LANCZOS)
    image.save(out_path, format="WEBP", quality=THUMBNAIL_QUALITY, method=4)
    return image.size


def image_thumbnail(source: Path, out_path: Path) -> tuple[int, int]:
    """Bounded WebP thumbnail of any image Pillow (or, as fallback, MuPDF) can decode."""
    try:
        with Image.open(source) as image:
            image.draft("RGB", (THUMBNAIL_MAX_SIZE[0] * 2, THUMBNAIL_MAX_SIZE[1] * 2))
            return _save_webp(ImageOps.exif_transpose(image), out_path)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        pass
    try:
        with fitz.open(str(source)) as doc:
            if doc.page_count == 0:
                raise ImageError("Cannot render an empty image.")
            return _page_thumbnail(doc[0], out_path)
    except (RuntimeError, ValueError) as exc:  # MuPDF raises RuntimeError subclasses
        raise ImageError("Source image cannot be decoded.") from exc


def viewport_thumbnail(screenshot: Path, out_path: Path, *, viewport: tuple[int, int]) -> None:
    """Thumbnail of the top (first viewport) of a possibly full-page screenshot."""
    with Image.open(screenshot) as image:
        top = image.crop((0, 0, min(image.width, viewport[0]), min(image.height, viewport[1])))
        _save_webp(top, out_path)


def pdf_first_page_thumbnail(pdf: Path, out_path: Path) -> tuple[int, int]:
    try:
        with fitz.open(str(pdf)) as doc:
            if doc.page_count == 0:
                raise ImageError("Cannot render an empty PDF.")
            return _page_thumbnail(doc[0], out_path)
    except RuntimeError as exc:
        raise ImageError("PDF cannot be opened.") from exc


def _page_thumbnail(page: Any, out_path: Path) -> tuple[int, int]:
    width, height = page.rect.width, page.rect.height
    if width <= 0 or height <= 0:
        raise ImageError("Cannot render a thumbnail for zero-sized content.")
    zoom = min(THUMBNAIL_MAX_SIZE[0] / width, THUMBNAIL_MAX_SIZE[1] / height, 2.0)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return _save_webp(image, out_path)


def render_pdf_page_jpeg(pdf: Path, page_index: int, *, zoom: float = 2.0) -> bytes:
    """One page as JPEG bytes (for OCR)."""
    with fitz.open(str(pdf)) as doc:
        pix = doc[page_index].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def text_thumbnail(title: str, body: str, out_path: Path) -> tuple[int, int]:
    width, height = TEXT_THUMBNAIL_SIZE
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = _font(16, mono=False)
    body_font = _font(10, mono=True)
    margin = 20
    y = margin
    for line in textwrap.wrap(title.strip()[:140], width=34)[:3]:
        draw.text((margin, y), line, fill="#17202a", font=title_font)
        y += 20
    y += 12
    for paragraph in body[:5000].splitlines():
        for line in textwrap.wrap(paragraph, width=52) or [""]:
            if y > height - margin - 12:
                image.save(out_path, format="WEBP", quality=THUMBNAIL_QUALITY, method=4)
                return image.size
            draw.text((margin, y), line, fill="#34495e", font=body_font)
            y += 13
    image.save(out_path, format="WEBP", quality=THUMBNAIL_QUALITY, method=4)
    return image.size


def text_pdf(title: str, text: str, out_path: Path, *, max_pages: int) -> None:
    """Paginated A4 PDF of plain text (Cyrillic-capable when a TTF font is installed)."""
    font_file = _font_path(mono=True)
    font_name = "body" if font_file else "cour"
    lines_per_page, chars_per_line, font_size, line_height = 64, 95, 9, 11.5
    lines: list[str] = []
    for paragraph in [title, "", *text.splitlines()]:
        lines.extend(textwrap.wrap(paragraph, width=chars_per_line) or [""])
    with fitz.open() as doc:
        for start in range(0, max(len(lines), 1), lines_per_page):
            if doc.page_count >= max_pages:
                break
            page = doc.new_page(width=595, height=842)
            if font_file:
                page.insert_font(fontname=font_name, fontfile=font_file)
            y = 54.0
            for line in lines[start : start + lines_per_page]:
                page.insert_text((48, y), line, fontsize=font_size, fontname=font_name)
                y += line_height
        if font_file:
            doc.subset_fonts()  # embed only used glyphs (a full TTF per page is megabytes)
        doc.save(str(out_path), garbage=4, deflate=True)


def image_for_ai(source: Path, mime_type: str | None, *, max_bytes: int) -> tuple[bytes, str]:
    """Image bytes acceptable to vision APIs: original when small and common, otherwise a
    downscaled JPEG. Raises ImageError if it cannot be produced within `max_bytes`."""
    size = source.stat().st_size
    if mime_type in AI_IMAGE_MIME_TYPES and size <= max_bytes:
        return source.read_bytes(), mime_type
    try:
        with Image.open(source) as image:
            image.draft("RGB", (AI_IMAGE_MAX_SIDE, AI_IMAGE_MAX_SIDE))
            converted = ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise ImageError("Image cannot be decoded for analysis.") from exc
    converted.thumbnail((AI_IMAGE_MAX_SIDE, AI_IMAGE_MAX_SIDE), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    converted.save(buffer, format="JPEG", quality=85)
    data = buffer.getvalue()
    if len(data) > max_bytes:
        raise ImageError("Image is too large for analysis.")
    return data, "image/jpeg"
