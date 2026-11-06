"""Pure helpers: titles, slugs, link extraction, media type detection, image headers."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from unicodedata import normalize
from urllib.parse import urlparse
from uuid import UUID

AUDIO_SUFFIXES = frozenset(
    {".aac", ".amr", ".flac", ".m4a", ".mp3", ".oga", ".ogg", ".opus", ".wav", ".weba"}
)
VIDEO_SUFFIXES = frozenset({".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"})
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})
TEXT_SUFFIXES = frozenset({".txt", ".md", ".markdown"})

_TITLE_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_TITLE_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_TITLE_CUSTOM_EMOJI_RE = re.compile(r"\{\{tg_emoji:[0-9]+\|([^}]+)\}\}")
_TITLE_INLINE_TAG_RE = re.compile(r"</?(?:u|b|i|s|em|strong|code|tg-spoiler)\b[^>]*>", re.I)
_TITLE_HEADING_PREFIX_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
_TITLE_BLOCKQUOTE_PREFIX_RE = re.compile(r"^\s{0,3}>\s+")
_TITLE_TASK_PREFIX_RE = re.compile(r"^\s{0,3}[-*+]\s+\[[ xX]\]\s+")
_TITLE_LIST_PREFIX_RE = re.compile(r"^\s{0,3}[-*+]\s+")
_TITLE_BOLD_STAR_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_TITLE_BOLD_UNDERSCORE_RE = re.compile(r"__(.+?)__", re.DOTALL)
_TITLE_STRIKE_RE = re.compile(r"~~(.+?)~~", re.DOTALL)
_TITLE_ITALIC_STAR_RE = re.compile(r"(?<!\*)\*(?!\*)(\S(?:[^*\n]*?\S)?)\*(?!\*)")
_TITLE_ITALIC_UNDERSCORE_RE = re.compile(
    r"(?<![A-Za-z0-9_])_(?!_)(\S(?:[^_\n]*?\S)?)_(?!_)(?![A-Za-z0-9_])"
)
_TITLE_INLINE_CODE_RE = re.compile(r"`+([^`]+?)`+")
_LINK_RE = re.compile(r"(?<!!)\[([^\]\n]+)\]\((https?://[^\s)]+)\)|(https?://\S+)")
_MARKDOWN_LINK_ONLY_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_JPEG_SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)
FAVICON_HOST = "favicon.yandex.net"


def slugify(value: str) -> str:
    normalized = normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    return _SLUG_RE.sub("-", normalized).strip("-")[:200].strip("-") or "item"


def as_uuid(ref: str) -> str | None:
    """Normalized UUID string if `ref` looks like one (note refs may be ids or slugs)."""
    try:
        return str(UUID(ref.strip()))
    except (ValueError, AttributeError):
        return None


def strip_title_markdown(value: str) -> str:
    """Remove Markdown / Telegram entity markers from a single-line title (keeps the text;
    custom emoji markers become their fallback emoji; whitespace is collapsed)."""
    text = value.replace("\r", " ").replace("\n", " ")
    text = _TITLE_CUSTOM_EMOJI_RE.sub(r"\1", text)
    text = _TITLE_HEADING_PREFIX_RE.sub("", text)
    text = _TITLE_BLOCKQUOTE_PREFIX_RE.sub("", text)
    text = _TITLE_TASK_PREFIX_RE.sub("", text)
    text = _TITLE_LIST_PREFIX_RE.sub("", text)
    text = _TITLE_IMAGE_RE.sub(r"\1", text)
    text = _TITLE_LINK_RE.sub(r"\1", text)
    text = _TITLE_INLINE_TAG_RE.sub("", text)
    text = _TITLE_BOLD_STAR_RE.sub(r"\1", text)
    text = _TITLE_BOLD_UNDERSCORE_RE.sub(r"\1", text)
    text = _TITLE_STRIKE_RE.sub(r"\1", text)
    text = _TITLE_INLINE_CODE_RE.sub(r"\1", text)
    text = _TITLE_ITALIC_STAR_RE.sub(r"\1", text)
    text = _TITLE_ITALIC_UNDERSCORE_RE.sub(r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_title(*candidates: str | None, max_length: int = 80) -> str:
    """First clean non-empty line among the candidates, truncated."""
    for candidate in candidates:
        if not candidate:
            continue
        for line in str(candidate).splitlines():
            cleaned = strip_title_markdown(line)
            if cleaned:
                return cleaned[:max_length]
    return ""


def markdown_link_with_favicon(url: str, *, label: str | None = None) -> str:
    parsed = urlparse(url)
    favicon_url = f"https://{FAVICON_HOST}/favicon/{parsed.hostname or url}"
    link_label = label.strip() if label and label.strip() else url
    return f"![favicon]({favicon_url}) [{link_label}]({url})"


def extract_links(text: str) -> tuple[list[str], str]:
    """HTTP(S) URLs in order of appearance (deduplicated) and the text with each link
    rewritten as a Markdown link with a favicon preview."""
    links: list[str] = []
    seen: set[str] = set()
    parts: list[str] = []
    last_end = 0
    for match in _LINK_RE.finditer(text):
        label, markdown_url, bare_url = match.group(1), match.group(2), match.group(3)
        raw = markdown_url or bare_url or ""
        url = raw.rstrip(".,;:!?)]\\'\">`") if bare_url else raw.rstrip(".,;:!?\\'\">`")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            parts.append(text[last_end : match.end()])
            last_end = match.end()
            continue
        parts.append(text[last_end : match.start()])
        parts.append(markdown_link_with_favicon(url, label=label))
        if url not in seen:
            seen.add(url)
            links.append(url)
        last_end = match.end() if markdown_url else match.start() + len(url)
    parts.append(text[last_end:])
    return links, "".join(parts)


def plain_url(value: str) -> str | None:
    candidate = value.strip()
    if not candidate or any(character.isspace() for character in candidate):
        return None
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        return None
    return candidate


def link_only_url(value: str) -> str | None:
    """The URL when the whole text is one link (bare, or `[url](url)`)."""
    plain = plain_url(value)
    if plain is not None:
        return plain
    match = _MARKDOWN_LINK_ONLY_RE.fullmatch(value.strip())
    if match is None:
        return None
    label = match.group(1).strip()
    url = match.group(2).rstrip(".,;:!?\\'\">`")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        return None
    return url if label == url else None


def link_host_title(url: str) -> str:
    return urlparse(url).hostname or url


def title_is_url_placeholder(title: str, url: str) -> bool:
    cleaned = strip_title_markdown(title)
    if not cleaned.startswith(("http://", "https://")):
        return False
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        return False
    return cleaned == url or url.startswith(cleaned) or cleaned.startswith(url)


def is_generated_favicon_url(url: str) -> bool:
    return urlparse(url).hostname == FAVICON_HOST


def media_type_for(filename: str, content_type: str | None) -> str:
    suffix = PurePosixPath(filename).suffix.lower()
    if content_type:
        if content_type.startswith("image/"):
            return "image"
        if content_type.startswith("audio/"):
            return "audio"
        if content_type.startswith("video/"):
            return "video"
        if content_type.startswith("text/"):
            return "text"
        if content_type == "application/ogg" and suffix not in VIDEO_SUFFIXES:
            return "audio"
    if suffix in TEXT_SUFFIXES:
        return "text"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in AUDIO_SUFFIXES:
        return "audio"
    if suffix in VIDEO_SUFFIXES:
        return "video"
    return "document"


def is_markdown_file(filename: str, mime_type: str | None) -> bool:
    return mime_type == "text/markdown" or PurePosixPath(filename).suffix.lower() in {
        ".md",
        ".markdown",
    }


def is_pdf_file(filename: str, mime_type: str | None) -> bool:
    return mime_type == "application/pdf" or PurePosixPath(filename).suffix.lower() == ".pdf"


def image_dimensions_from_header(data: bytes) -> tuple[int, int] | None:
    """Width/height from the first bytes of a PNG, GIF, WebP or JPEG file."""

    def valid(width: int, height: int) -> tuple[int, int] | None:
        return (width, height) if width > 0 and height > 0 else None

    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return valid(int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big"))
    if data.startswith((b"GIF87a", b"GIF89a")) and len(data) >= 10:
        return valid(int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little"))
    if data.startswith(b"RIFF") and len(data) >= 30 and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8 ":
            return valid(
                int.from_bytes(data[26:28], "little") & 0x3FFF,
                int.from_bytes(data[28:30], "little") & 0x3FFF,
            )
        if chunk == b"VP8L":
            bits = int.from_bytes(data[21:25], "little")
            return valid((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
        if chunk == b"VP8X":
            return valid(
                int.from_bytes(data[24:27], "little") + 1,
                int.from_bytes(data[27:30], "little") + 1,
            )
    if data.startswith(b"\xff\xd8"):
        return _jpeg_dimensions(data)
    return None


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        while marker == 0xFF and index < len(data):
            marker = data[index]
            index += 1
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > len(data):
            return None
        segment_length = int.from_bytes(data[index : index + 2], "big")
        if segment_length < 2 or index + segment_length > len(data):
            return None
        if marker in _JPEG_SOF_MARKERS:
            height = int.from_bytes(data[index + 3 : index + 5], "big")
            width = int.from_bytes(data[index + 5 : index + 7], "big")
            return (width, height) if width > 0 and height > 0 else None
        index += segment_length
    return None


def optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    return str(value)


def optional_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None


def optional_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def optional_list(value: Any) -> list[Any] | None:
    return value if isinstance(value, list) else None


def telegram_chat_type(origin: dict[str, Any] | None) -> str | None:
    if not isinstance(origin, dict):
        return None
    origin_type = origin.get("type")
    mapping = {"user": "private", "chat": "group", "channel": "channel"}
    if isinstance(origin_type, str) and origin_type in mapping:
        return mapping[origin_type]
    return str(origin_type) if origin_type else None
