from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.modules.content.models import ContentAsset


@dataclass(frozen=True, slots=True)
class ExtractionPage:
    page_number: int
    method: str
    char_count: int
    quality: float | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "method": self.method,
            "char_count": self.char_count,
            "quality": self.quality,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class ExtractionSection:
    kind: str
    heading: str | None
    char_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "heading": self.heading,
            "char_count": self.char_count,
        }


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    markdown: str
    plain_text: str
    source_kind: str
    method: str
    warnings: list[str] = field(default_factory=list)
    pages: list[ExtractionPage] = field(default_factory=list)
    sections: list[ExtractionSection] = field(default_factory=list)
    quality: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def metadata_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "method": self.method,
            "quality": self.quality,
            "warnings": list(self.warnings),
            "pages": [page.to_dict() for page in self.pages],
            "sections": [section.to_dict() for section in self.sections],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ExtractorContext:
    fetch_webpage_html: Callable[[str], str]
    link_url: Callable[[ContentAsset, Path], str]
    convert_office_to_pdf: Callable[[Path], Path | None]


def normalize_blank_lines(value: str) -> str:
    lines = [line.rstrip() for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    result: list[str] = []
    blank = False
    for line in lines:
        if not line.strip():
            if not blank:
                result.append("")
            blank = True
            continue
        result.append(line)
        blank = False
    return "\n".join(result).strip()


def plain_text_from_markdown(markdown: str) -> str:
    text = markdown
    replacements = [
        ("**", ""),
        ("__", ""),
        ("`", ""),
        ("> ", ""),
        ("# ", ""),
        ("## ", ""),
        ("### ", ""),
        ("#### ", ""),
        ("##### ", ""),
        ("###### ", ""),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return normalize_blank_lines(text)
