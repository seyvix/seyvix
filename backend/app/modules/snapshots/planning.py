"""Which snapshot outputs an asset gets, given server defaults and per-user overrides."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Final, Literal

from app.core.config import Settings
from app.modules.snapshots.models import SnapshotUserSettings

SnapshotJobType = Literal[
    "markdown", "thumbnail", "thumbnail_text", "screenshot", "webpage_html", "pdf"
]
SNAPSHOT_JOB_TYPES: Final[tuple[SnapshotJobType, ...]] = (
    "markdown",
    "thumbnail",
    "thumbnail_text",
    "screenshot",
    "webpage_html",
    "pdf",
)

MARKDOWN_SUFFIXES: Final = frozenset({".md", ".markdown"})
TEXT_THUMBNAIL_SUFFIXES: Final = frozenset({".md", ".markdown", ".txt"})
TEXT_PDF_SUFFIXES: Final = frozenset({".csv", ".htm", ".html", ".json", ".txt"})
OFFICE_SUFFIXES: Final = frozenset(
    {".doc", ".docx", ".odp", ".ods", ".odt", ".ppt", ".pptx", ".rtf", ".xls", ".xlsx"}
)
OFFICE_MIME_TYPES: Final = frozenset(
    {
        "application/msword",
        "application/rtf",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        "application/vnd.oasis.opendocument.presentation",
        "application/vnd.oasis.opendocument.spreadsheet",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
)
TEXT_PDF_MIME_TYPES: Final = frozenset(
    {"application/json", "text/csv", "text/html", "text/markdown", "text/plain"}
)


@dataclass(frozen=True, slots=True)
class EffectiveSnapshotSettings:
    screenshot: bool
    webpage_html: bool
    pdf: bool
    markdown: bool


@dataclass(frozen=True, slots=True)
class AssetFacts:
    """The asset attributes planning and processing depend on (no ORM state)."""

    media_type: str
    mime_type: str | None
    filename: str

    @property
    def suffix(self) -> str:
        return PurePosixPath(self.filename).suffix.lower()

    @property
    def is_link(self) -> bool:
        return self.media_type == "link"

    @property
    def is_pdf(self) -> bool:
        return self.mime_type == "application/pdf" or self.suffix == ".pdf"

    @property
    def uses_text_thumbnail(self) -> bool:
        return (
            self.media_type == "text"
            or self.mime_type in {"text/markdown", "text/plain"}
            or self.suffix in TEXT_THUMBNAIL_SUFFIXES
        )

    @property
    def wants_pdf(self) -> bool:
        if self.is_pdf:
            return False
        if self.mime_type in OFFICE_MIME_TYPES or self.mime_type in TEXT_PDF_MIME_TYPES:
            return True
        if self.media_type == "document":
            return self.suffix in OFFICE_SUFFIXES | TEXT_PDF_SUFFIXES
        if self.media_type == "text":
            return self.suffix in MARKDOWN_SUFFIXES | TEXT_PDF_SUFFIXES
        return self.is_link


def effective_settings(
    settings: Settings, stored: SnapshotUserSettings | None
) -> EffectiveSnapshotSettings:
    def pick(override: bool | None, default: bool) -> bool:
        return default if override is None else override

    return EffectiveSnapshotSettings(
        screenshot=pick(
            stored.archive_as_screenshot if stored else None, settings.snapshot_screenshot_enabled
        ),
        webpage_html=pick(
            stored.archive_as_webpage_html if stored else None,
            settings.snapshot_webpage_html_enabled,
        ),
        pdf=pick(stored.archive_as_pdf if stored else None, settings.snapshot_page_pdf_enabled),
        markdown=pick(stored.archive_as_markdown if stored else None, True),
    )


def text_extractable(asset: AssetFacts, settings: Settings) -> bool:
    """Images and media only yield text through AI; without it no markdown job is planned."""
    ai = settings.ai_enabled
    if asset.media_type == "image":
        return ai and (settings.ai_ocr_enabled or settings.ai_vision_enabled)
    if asset.media_type == "audio":
        return ai and settings.ai_transcription_enabled
    if asset.media_type == "video":
        return ai and (settings.ai_transcription_enabled or settings.ai_vision_enabled)
    return True


def plan_snapshot_job_types(
    asset: AssetFacts, effective: EffectiveSnapshotSettings, *, extract_text: bool = True
) -> tuple[SnapshotJobType, ...]:
    """Markdown is produced whenever possible: it is the text representation search and
    tagging use (the user `markdown` toggle only controls its display)."""
    job_types: list[SnapshotJobType] = ["markdown"] if extract_text else []
    job_types.append("thumbnail_text" if asset.uses_text_thumbnail else "thumbnail")
    if effective.pdf and asset.wants_pdf:
        job_types.append("pdf")
    if asset.is_link:
        if effective.screenshot:
            job_types.append("screenshot")
        if effective.webpage_html:
            job_types.append("webpage_html")
    return tuple(job_types)


def source_fingerprint(
    *, storage_key: str, size_bytes: int, checksum: str | None, text_content: str | None
) -> str:
    digest = hashlib.sha256()
    for part in (storage_key, str(size_bytes), checksum or "", text_content or ""):
        digest.update(part.encode("utf-8", errors="replace"))
        digest.update(b"\x00")
    return digest.hexdigest()
