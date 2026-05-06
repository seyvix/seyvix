from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

MIME_TO_EXT: dict[str, str] = {
    "text/css": ".css",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
    "font/woff": ".woff",
    "font/woff2": ".woff2",
    "font/ttf": ".ttf",
    "font/otf": ".otf",
    "application/font-woff": ".woff",
    "application/font-woff2": ".woff2",
    "application/x-font-ttf": ".ttf",
}

RESOURCE_WHITELIST: frozenset[str] = frozenset(MIME_TO_EXT.keys())

_URL_RE = re.compile(r"url\(([^)]+)\)", re.IGNORECASE)
_TAG_ATTRS: tuple[tuple[str, str], ...] = (
    ("img", "src"),
    ("link", "href"),
    ("source", "src"),
    ("input", "src"),
    ("video", "src"),
    ("audio", "src"),
    ("embed", "src"),
    ("track", "src"),
)


def ext_for_mime(mime_type: str) -> str:
    base = mime_type.split(";")[0].strip().lower()
    return MIME_TO_EXT.get(base, ".bin")


def rewrite_css(css_text: str, css_base_url: str, manifest: dict[str, str]) -> str:
    return _replace_css_urls(css_text, css_base_url, manifest)


def rewrite_html(html: str, page_url: str, manifest: dict[str, str]) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all("script"):
        tag.decompose()

    for tag in soup.find_all(True):
        if not isinstance(tag, Tag):
            continue
        for attr in list(tag.attrs):
            if isinstance(attr, str) and attr.lower().startswith("on"):
                del tag[attr]
        href = tag.get("href", "")
        if isinstance(href, str) and href.strip().lower().startswith("javascript:"):
            tag["href"] = "#"

    for tag_name, attr in _TAG_ATTRS:
        for el in soup.find_all(tag_name, **{attr: True}):
            if not isinstance(el, Tag):
                continue
            raw = el.get(attr, "")
            if not isinstance(raw, str):
                continue
            resolved = _resolve(page_url, raw)
            if resolved and resolved in manifest:
                el[attr] = manifest[resolved]

    for el in soup.find_all(True, srcset=True):
        if not isinstance(el, Tag):
            continue
        parts = []
        for part in str(el["srcset"]).split(","):
            pieces = part.strip().split()
            if pieces:
                resolved = _resolve(page_url, pieces[0])
                if resolved and resolved in manifest:
                    pieces[0] = manifest[resolved]
            parts.append(" ".join(pieces))
        el["srcset"] = ", ".join(parts)

    for el in soup.find_all(True, style=True):
        if not isinstance(el, Tag):
            continue
        style = el.get("style", "")
        if isinstance(style, str):
            el["style"] = _replace_css_urls(style, page_url, manifest)

    for el in soup.find_all("style"):
        if not isinstance(el, Tag):
            continue
        if el.string:
            el.string = _replace_css_urls(el.string, page_url, manifest)

    return str(soup)


def _replace_css_urls(css_text: str, base_url: str, manifest: dict[str, str]) -> str:
    def replacer(match: re.Match[str]) -> str:
        raw = match.group(1).strip()
        if raw and raw[0] in "\"'":
            quote = raw[0]
            raw = raw[1:-1] if raw.endswith(quote) else raw[1:]
        else:
            quote = ""
        resolved = _resolve(base_url, raw)
        if resolved and resolved in manifest:
            return f"url({quote}{manifest[resolved]}{quote})"
        return match.group(0)

    return _URL_RE.sub(replacer, css_text)


def _resolve(base_url: str, url: str) -> str | None:
    url = url.strip()
    if not url:
        return None
    lower = url.lower()
    if lower.startswith(("data:", "#", "javascript:")):
        return None
    return urljoin(base_url, url)
