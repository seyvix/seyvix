"""Fetch a web page `<title>` for new link notes.

Bounded in time and size and protected against SSRF: every hop (including redirects) must
resolve only to public addresses, and the connection is pinned to the validated address so
DNS rebinding cannot redirect it to an internal host.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from html import unescape
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

FETCH_TIMEOUT_SECONDS = 3.0
MAX_BODY_BYTES = 256 * 1024
MAX_REDIRECTS = 3
ALLOWED_PORTS = frozenset({80, 443, 8080, 8443})
_TITLE_RE = re.compile(rb"<title\b[^>]*>(.*?)</title\s*>", re.IGNORECASE | re.DOTALL)
_CHARSET_RE = re.compile(r"charset=([\w-]+)", re.IGNORECASE)
_HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    "User-Agent": "Mozilla/5.0 (compatible; SeyvixBot/1.0; +link-title)",
}


class UnsafeUrlError(Exception):
    pass


async def _resolve_public(host: str, port: int) -> str:
    """Resolve `host` and return one address; reject if any address is not public."""
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addresses = [literal]
    else:
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise UnsafeUrlError(f"cannot resolve {host}") from exc
        addresses = [ipaddress.ip_address(info[4][0]) for info in infos]
    if not addresses or any(not address.is_global or address.is_multicast for address in addresses):
        raise UnsafeUrlError(f"{host} resolves to a non-public address")
    return str(addresses[0])


def _target(url: str) -> tuple[str, str, int]:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise UnsafeUrlError("unsupported url")
    if parts.username or parts.password:
        raise UnsafeUrlError("credentials in url")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise UnsafeUrlError(f"port {port} not allowed")
    return parts.scheme, parts.hostname, port


async def _fetch_title(client: httpx.AsyncClient, url: str) -> str | None:
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        scheme, host, port = _target(current)
        address = await _resolve_public(host, port)
        parts = urlsplit(current)
        ip_host = f"[{address}]" if ":" in address else address
        pinned = urlunsplit((scheme, f"{ip_host}:{port}", parts.path or "/", parts.query, ""))
        request = client.build_request(
            "GET",
            pinned,
            headers={**_HEADERS, "Host": parts.netloc.rsplit("@", 1)[-1]},
            extensions={"sni_hostname": host},
        )
        response = await client.send(request, stream=True)
        try:
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    return None
                current = urljoin(current, location)
                continue
            if response.status_code >= 400:
                logger.info("content.link_title.bad_status", url=url, status=response.status_code)
                return None
            content_type = response.headers.get("content-type", "")
            if content_type and "html" not in content_type.lower():
                return None
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) >= MAX_BODY_BYTES or b"</title" in body.lower():
                    break
            return _title_from_html(bytes(body[:MAX_BODY_BYTES]), content_type)
        finally:
            await response.aclose()
    return None


def _title_from_html(body: bytes, content_type: str) -> str | None:
    match = _TITLE_RE.search(body)
    if match is None:
        return None
    charset_match = _CHARSET_RE.search(content_type)
    encoding = charset_match.group(1) if charset_match else "utf-8"
    try:
        raw = match.group(1).decode(encoding, errors="replace")
    except LookupError:
        raw = match.group(1).decode("utf-8", errors="replace")
    title = re.sub(r"\s+", " ", unescape(raw)).strip()
    return title[:512] or None


async def fetch_page_title(url: str) -> str | None:
    """Best-effort `<title>` of `url`; None on any failure (never raises)."""
    try:
        async with asyncio.timeout(FETCH_TIMEOUT_SECONDS):
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=FETCH_TIMEOUT_SECONDS,
                trust_env=False,
            ) as client:
                return await _fetch_title(client, url)
    except UnsafeUrlError as exc:
        logger.info("content.link_title.rejected", url=url, reason=str(exc))
    except (TimeoutError, httpx.HTTPError, OSError) as exc:
        logger.info("content.link_title.failed", url=url, error=str(exc))
    return None
