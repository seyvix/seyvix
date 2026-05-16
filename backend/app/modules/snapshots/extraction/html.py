from __future__ import annotations

import importlib
import re
from html import unescape
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from app.modules.snapshots.extraction.core import (
    ExtractionResult,
    ExtractionSection,
    normalize_blank_lines,
    plain_text_from_markdown,
)

BOILERPLATE_PATTERN = re.compile(
    r"(?:^|[-_\s])("
    r"ad|ads|advert|advertisement|banner|cookie|consent|newsletter|subscribe|"
    r"sidebar|social|share|promo|popup|modal|comments|related|recommend"
    r")(?:$|[-_\s])",
    re.IGNORECASE,
)


def html_to_markdown(
    value: str,
    *,
    source_url: str | None = None,
    source_kind: str = "html",
) -> ExtractionResult:
    trafilatura_result = _try_trafilatura(value, source_url=source_url)
    if trafilatura_result:
        return ExtractionResult(
            markdown=trafilatura_result,
            plain_text=plain_text_from_markdown(trafilatura_result),
            source_kind=source_kind,
            method="trafilatura",
            quality=_quality_score(trafilatura_result),
            metadata={"source_url": source_url} if source_url else {},
        )

    soup = BeautifulSoup(value, "html.parser")
    _remove_noise(soup)
    root = _main_content_root(soup)
    markdown = normalize_blank_lines(_render_children(root, source_url=source_url))
    title = _first_heading(markdown) or _title_text(soup)
    sections = []
    if title:
        sections.append(ExtractionSection(kind="main", heading=title, char_count=len(markdown)))
    return ExtractionResult(
        markdown=markdown,
        plain_text=plain_text_from_markdown(markdown),
        source_kind=source_kind,
        method="beautifulsoup",
        sections=sections,
        quality=_quality_score(markdown),
        metadata={"source_url": source_url} if source_url else {},
    )


def _try_trafilatura(value: str, *, source_url: str | None) -> str | None:
    try:
        trafilatura = importlib.import_module("trafilatura")
    except ImportError:
        return None
    extracted = trafilatura.extract(
        value,
        url=source_url,
        output_format="markdown",
        include_links=True,
        include_tables=True,
        favor_precision=True,
    )
    return normalize_blank_lines(extracted or "") or None


def _remove_noise(soup: BeautifulSoup) -> None:
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form", "header", "footer"]):
        tag.decompose()
    for tag in soup.find_all(["nav", "aside"]):
        tag.decompose()
    for tag in list(soup.find_all(True)):
        if not isinstance(tag, Tag):
            continue
        values = " ".join(_attribute_values(tag, "class", "id", "role", "aria-label"))
        if values and BOILERPLATE_PATTERN.search(values):
            tag.decompose()


def _main_content_root(soup: BeautifulSoup) -> Tag:
    for selector in (
        "article",
        "main",
        "[role='main']",
        ".article",
        ".post",
        ".entry-content",
        ".content",
    ):
        candidate = soup.select_one(selector)
        if isinstance(candidate, Tag) and len(candidate.get_text(" ", strip=True)) > 0:
            return candidate
    body = soup.body
    return body if isinstance(body, Tag) else soup


def _attribute_values(tag: Tag, *names: str) -> list[str]:
    values: list[str] = []
    for name in names:
        raw = tag.get(name)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw if item)
        elif raw:
            values.append(str(raw))
    return values


def _render_children(tag: Tag, *, source_url: str | None) -> str:
    rendered = [_render_node(child, source_url=source_url) for child in tag.children]
    return "\n\n".join(part for part in rendered if part.strip())


def _render_node(node: Any, *, source_url: str | None) -> str:
    if isinstance(node, NavigableString):
        return _collapse_ws(str(node))
    if not isinstance(node, Tag):
        return ""
    name = node.name.lower()
    if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        level = min(int(name[1]), 6)
        return f"{'#' * level} {_inline_text(node, source_url=source_url)}".strip()
    if name == "p":
        return _inline_text(node, source_url=source_url)
    if name in {"ul", "ol"}:
        return _render_list(node, ordered=name == "ol", source_url=source_url)
    if name == "li":
        return _inline_text(node, source_url=source_url)
    if name == "blockquote":
        text = normalize_blank_lines(_render_children(node, source_url=source_url))
        return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())
    if name in {"pre", "code"}:
        text = node.get_text("\n", strip=False).strip("\n")
        return f"```\n{text}\n```" if text else ""
    if name == "table":
        return _render_table(node, source_url=source_url)
    if name in {"br"}:
        return "\n"
    return _render_children(node, source_url=source_url)


def _render_list(tag: Tag, *, ordered: bool, source_url: str | None) -> str:
    lines: list[str] = []
    for index, item in enumerate(tag.find_all("li", recursive=False), start=1):
        marker = f"{index}." if ordered else "-"
        text = normalize_blank_lines(_inline_text(item, source_url=source_url))
        if text:
            lines.append(f"{marker} {text}")
    return "\n".join(lines)


def _render_table(tag: Tag, *, source_url: str | None) -> str:
    rows: list[list[str]] = []
    for tr in tag.find_all("tr"):
        cells = [
            _inline_text(cell, source_url=source_url).replace("|", "\\|")
            for cell in tr.find_all(["th", "td"], recursive=False)
        ]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    header = padded[0]
    body = padded[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _inline_text(tag: Tag, *, source_url: str | None) -> str:
    parts: list[str] = []
    for child in tag.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
            continue
        if not isinstance(child, Tag):
            continue
        name = child.name.lower()
        text = _inline_text(child, source_url=source_url)
        if not text:
            continue
        if name == "a":
            href = child.get("href")
            if href:
                parts.append(f"[{text}]({urljoin(source_url or '', str(href))})")
            else:
                parts.append(text)
        elif name in {"strong", "b"}:
            parts.append(f"**{text}**")
        elif name in {"em", "i"}:
            parts.append(f"_{text}_")
        elif name == "code":
            parts.append(f"`{text}`")
        elif name == "br":
            parts.append("\n")
        else:
            parts.append(text)
    return _collapse_ws("".join(parts))


def _collapse_ws(value: str) -> str:
    return unescape(re.sub(r"[ \t\n\r\f\v]+", " ", value)).strip()


def _title_text(soup: BeautifulSoup) -> str | None:
    if soup.title is None:
        return None
    value = soup.title.get_text(" ", strip=True)
    return value or None


def _first_heading(markdown: str) -> str | None:
    for line in markdown.splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip() or None
    return None


def _quality_score(markdown: str) -> float:
    text = plain_text_from_markdown(markdown)
    if not text:
        return 0.0
    words = len(text.split())
    return min(1.0, words / 80)
