"""Outbound network guard for snapshotting user-supplied URLs (SSRF protection).

Every byte the snapshot worker fetches from the internet — Chromium navigations, redirects,
subresources, websockets and the plain-HTTP fallback — goes through `EgressProxy`, a tiny
local HTTP/CONNECT proxy. It resolves each destination itself, refuses non-public addresses
and connects to the exact IP it validated, so redirects and DNS rebinding cannot reach
loopback, private networks or cloud metadata endpoints.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import socket
from typing import Final
from urllib.parse import urlsplit

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

MAX_HEAD_BYTES: Final = 64 * 1024
CONNECT_TIMEOUT_SECONDS: Final = 10.0
IDLE_TIMEOUT_SECONDS: Final = 60.0
PIPE_CHUNK: Final = 64 * 1024
FETCH_MAX_BYTES: Final = 5 * 1024 * 1024
FETCH_TIMEOUT_SECONDS: Final = 20.0
FETCH_USER_AGENT: Final = "Mozilla/5.0 (compatible; SeyvixSnapshot/1.0)"
_HOP_BY_HOP: Final = frozenset(
    {b"connection", b"proxy-connection", b"proxy-authorization", b"keep-alive"}
)


class BlockedDestinationError(Exception):
    """The URL/host is not a public internet destination."""


class FetchError(Exception):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def is_public_address(address: IPAddress) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def parse_public_url(url: str) -> tuple[str, int]:
    """Syntactic URL check; returns (host, port)."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise BlockedDestinationError("Only HTTP and HTTPS URLs can be snapshotted.")
    host = parts.hostname.casefold().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        raise BlockedDestinationError("Local URLs cannot be snapshotted.")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise BlockedDestinationError("Invalid URL port.") from exc
    return host, port


async def resolve_public(host: str, port: int) -> list[str]:
    """Resolve `host` and return its addresses; refuse if ANY of them is non-public."""
    host = host.strip("[]")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                host, port, type=socket.SOCK_STREAM
            )
        except OSError as exc:
            raise BlockedDestinationError(f"Cannot resolve host: {host}") from exc
        addresses = list(dict.fromkeys(str(info[4][0]) for info in infos))
    else:
        addresses = [str(literal)]
    if not addresses:
        raise BlockedDestinationError(f"Cannot resolve host: {host}")
    if not all(is_public_address(ipaddress.ip_address(item)) for item in addresses):
        raise BlockedDestinationError("Private or local addresses cannot be snapshotted.")
    return addresses


async def validate_public_url(url: str) -> None:
    host, port = parse_public_url(url)
    await resolve_public(host, port)


class EgressProxy:
    """Local forward proxy enforcing public-only destinations. Start lazily, share per process."""

    def __init__(self) -> None:
        self._server: asyncio.Server | None = None
        self._url: str | None = None
        self._lock = asyncio.Lock()
        self._connections: set[asyncio.Task[None]] = set()

    async def url(self) -> str:
        async with self._lock:
            if self._url is None:
                self._server = await asyncio.start_server(
                    self._on_client, "127.0.0.1", 0, limit=MAX_HEAD_BYTES
                )
                port = self._server.sockets[0].getsockname()[1]
                self._url = f"http://127.0.0.1:{port}"
            return self._url

    async def aclose(self) -> None:
        async with self._lock:
            if self._server is not None:
                self._server.close()
                for task in list(self._connections):
                    task.cancel()
                await asyncio.gather(*self._connections, return_exceptions=True)
                with contextlib.suppress(Exception):
                    await self._server.wait_closed()
            self._server = None
            self._url = None

    async def _on_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._connections.add(task)
        try:
            await self._serve(reader, writer)
        except (TimeoutError, ConnectionError, asyncio.IncompleteReadError):
            pass  # client or upstream went away; nothing to report
        except asyncio.LimitOverrunError:
            await _reply(writer, b"431 Request Header Fields Too Large")
        finally:
            writer.close()
            if task is not None:
                self._connections.discard(task)

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), IDLE_TIMEOUT_SECONDS)
        request_line, _, header_block = head.partition(b"\r\n")
        try:
            method, target, version = request_line.decode("latin-1").split(" ", 2)
        except ValueError:
            await _reply(writer, b"400 Bad Request")
            return

        if method.upper() == "CONNECT":
            host, _, port_text = target.rpartition(":")
            if not host or not port_text.isdigit():
                await _reply(writer, b"400 Bad Request")
                return
            upstream = await self._open(writer, host, int(port_text))
            if upstream is None:
                return
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
            await _pipe(reader, writer, *upstream)
            return

        parts = urlsplit(target)
        if parts.scheme != "http" or not parts.hostname:
            await _reply(writer, b"400 Bad Request")
            return
        upstream = await self._open(writer, parts.hostname, parts.port or 80)
        if upstream is None:
            return
        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"
        headers = [
            line
            for line in header_block.split(b"\r\n")
            if line and line.split(b":", 1)[0].strip().lower() not in _HOP_BY_HOP
        ]
        # One request per upstream connection keeps the proxy stateless.
        new_head = b"\r\n".join(
            [f"{method} {path} {version}".encode("latin-1"), *headers, b"Connection: close"]
        )
        upstream[1].write(new_head + b"\r\n\r\n")
        await _pipe(reader, writer, *upstream)

    async def _open(
        self, writer: asyncio.StreamWriter, host: str, port: int
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter] | None:
        try:
            addresses = await resolve_public(host, port)
        except BlockedDestinationError as exc:
            logger.info("snapshot.egress.blocked", host=host, port=port, reason=str(exc))
            await _reply(writer, b"403 Forbidden")
            return None
        for address in addresses:
            try:
                return await asyncio.wait_for(
                    asyncio.open_connection(address, port), CONNECT_TIMEOUT_SECONDS
                )
            except (OSError, TimeoutError):
                continue
        await _reply(writer, b"502 Bad Gateway")
        return None


async def _reply(writer: asyncio.StreamWriter, status: bytes) -> None:
    with contextlib.suppress(ConnectionError):
        writer.write(b"HTTP/1.1 " + status + b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        await writer.drain()


async def _pipe(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    upstream_reader: asyncio.StreamReader,
    upstream_writer: asyncio.StreamWriter,
) -> None:
    async def copy(source: asyncio.StreamReader, sink: asyncio.StreamWriter) -> None:
        while True:
            chunk = await asyncio.wait_for(source.read(PIPE_CHUNK), IDLE_TIMEOUT_SECONDS)
            if not chunk:
                return
            sink.write(chunk)
            await sink.drain()

    tasks = [
        asyncio.create_task(copy(client_reader, upstream_writer)),
        asyncio.create_task(copy(upstream_reader, client_writer)),
    ]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        upstream_writer.close()


async def fetch_html(url: str, proxy: EgressProxy) -> tuple[str, str]:
    """Plain HTTP fetch of a page through the egress proxy (redirect hops are re-validated by
    the proxy). Returns (final_url, html); the body is capped at FETCH_MAX_BYTES."""
    await validate_public_url(url)
    try:
        async with (
            httpx.AsyncClient(
                proxy=await proxy.url(),
                follow_redirects=True,
                max_redirects=5,
                timeout=FETCH_TIMEOUT_SECONDS,
                headers={"User-Agent": FETCH_USER_AGENT},
            ) as client,
            client.stream("GET", url) as response,
        ):
            if response.status_code >= 400:
                raise FetchError(
                    f"Webpage returned HTTP {response.status_code}.",
                    retryable=response.status_code >= 500 or response.status_code == 429,
                )
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) >= FETCH_MAX_BYTES:
                    break
            encoding = response.encoding or "utf-8"
            return str(response.url), bytes(body).decode(encoding, errors="replace")
    except httpx.ProxyError as exc:
        # The egress proxy refused (non-public destination) or could not reach the host.
        raise FetchError(f"Webpage is not reachable: {exc}", retryable=False) from exc
    except httpx.HTTPError as exc:
        raise FetchError(f"Failed to fetch webpage: {exc}", retryable=True) from exc
