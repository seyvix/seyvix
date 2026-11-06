"""Headless Chromium for link snapshots (async Playwright).

One browser per worker process, started lazily, shared by concurrent jobs (a fresh
incognito context per page) and shut down after `snapshot_browser_idle_seconds` of
inactivity. All browser traffic goes through the egress proxy (SSRF guard). One `render()`
produces every output a link job needs from a single page load.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit

from app.core.config import Settings
from app.core.logging import get_logger
from app.modules.snapshots.egress import (
    BlockedDestinationError,
    EgressProxy,
    parse_public_url,
    resolve_public,
)
from app.modules.snapshots.errors import SnapshotError
from app.modules.snapshots.rewriter import RESOURCE_WHITELIST, ext_for_mime

if TYPE_CHECKING:
    from playwright.async_api import Browser, Page, Playwright, Request, Response
    from playwright.async_api import Route as PlaywrightRoute

logger = get_logger(__name__)

VIEWPORT: Final = (1280, 800)
NAVIGATION_TIMEOUT_MS: Final = 20_000
LOAD_STATE_TIMEOUT_MS: Final = 5_000
ACTION_TIMEOUT_MS: Final = 15_000
SCREENSHOT_MAX_HEIGHT: Final = 6_000
SCREENSHOT_QUALITY: Final = 80
CLOSE_TIMEOUT_SECONDS: Final = 10.0
ARCHIVE_MAX_RESOURCES: Final = 300
ARCHIVE_MAX_RESOURCE_BYTES: Final = 5 * 1024 * 1024
ARCHIVE_MAX_TOTAL_BYTES: Final = 30 * 1024 * 1024
LAUNCH_ARGS: Final = (
    "--no-sandbox",  # containers run without user namespaces; isolation = egress proxy + ctx
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-sync",
    "--mute-audio",
    "--no-first-run",
    "--renderer-process-limit=2",
    "--disable-features=Translate,MediaRouter,OptimizationHints,BackForwardCache",
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--js-flags=--max-old-space-size=256",
)


@dataclass(frozen=True, slots=True)
class RenderRequest:
    url: str
    out_dir: Path
    html: bool = False
    screenshot: bool = False  # viewport screenshot (thumbnail source)
    full_page: bool = False  # capped full-page screenshot instead of viewport
    pdf: bool = False
    archive: bool = False  # capture static resources for the HTML archive

    @property
    def visual(self) -> bool:
        return self.screenshot or self.full_page or self.pdf or self.archive


@dataclass(frozen=True, slots=True)
class ArchivedResource:
    original_url: str
    filename: str
    content_type: str


@dataclass(slots=True)
class PageCapture:
    url: str
    html: str | None = None
    screenshot: Path | None = None
    pdf: Path | None = None
    resources: list[ArchivedResource] = field(default_factory=list)


class BrowserManager:
    def __init__(self, settings: Settings, egress: EgressProxy) -> None:
        self.settings = settings
        self.egress = egress
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()
        self._active = 0
        self._idle_task: asyncio.Task[None] | None = None
        self._user_agent: str | None = None

    async def render(self, request: RenderRequest) -> PageCapture:
        """Load `request.url` once and capture the requested outputs.

        Raises SnapshotError (retryable for transient navigation failures)."""
        try:
            host, port = parse_public_url(request.url)
            await resolve_public(host, port)
        except BlockedDestinationError as exc:
            raise SnapshotError(str(exc)) from exc
        browser = await self._acquire()
        try:
            async with asyncio.timeout(self.settings.snapshot_timeout_seconds):
                return await self._render(browser, request)
        except TimeoutError as exc:
            raise SnapshotError("Page rendering timed out.", retryable=True) from exc
        finally:
            await self._release()

    async def aclose(self) -> None:
        async with self._lock:
            if self._idle_task is not None:
                self._idle_task.cancel()
                self._idle_task = None
            await self._shutdown()

    # --- lifecycle -----------------------------------------------------------------------
    async def _acquire(self) -> Browser:
        async with self._lock:
            self._active += 1
            if self._idle_task is not None:
                self._idle_task.cancel()
                self._idle_task = None
            if self._browser is None or not self._browser.is_connected():
                try:
                    await self._start()
                except SnapshotError:
                    self._active -= 1
                    raise
            assert self._browser is not None
            return self._browser

    async def _release(self) -> None:
        async with self._lock:
            self._active -= 1
            if self._active == 0 and self._browser is not None:
                self._idle_task = asyncio.create_task(self._close_when_idle())

    async def _close_when_idle(self) -> None:
        await asyncio.sleep(self.settings.snapshot_browser_idle_seconds)
        async with self._lock:
            if self._active == 0:
                logger.info("snapshot.browser.idle_shutdown")
                await self._shutdown()
            self._idle_task = None

    async def _start(self) -> None:
        await self._shutdown()
        try:
            from playwright.async_api import Error as PlaywrightError
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise SnapshotError("Playwright is not installed on the server.") from exc
        proxy_url = await self.egress.url()
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=list(LAUNCH_ARGS),
                # `<-loopback>` makes Chromium send even localhost traffic to the proxy.
                proxy={"server": proxy_url, "bypass": "<-loopback>"},
            )
        except PlaywrightError as exc:
            await self._shutdown()
            raise SnapshotError(f"Chromium cannot be started: {exc}", retryable=True) from exc
        major = self._browser.version.split(".", 1)[0]
        self._user_agent = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{major}.0.0.0 Safari/537.36"
        )
        logger.info("snapshot.browser.started", version=self._browser.version)

    async def _shutdown(self) -> None:
        browser, playwright = self._browser, self._playwright
        self._browser = self._playwright = None
        if browser is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(browser.close(), CLOSE_TIMEOUT_SECONDS)
        if playwright is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(playwright.stop(), CLOSE_TIMEOUT_SECONDS)

    # --- rendering -----------------------------------------------------------------------
    async def _render(self, browser: Browser, request: RenderRequest) -> PageCapture:
        from playwright.async_api import Error as PlaywrightError

        context = await browser.new_context(
            viewport={"width": VIEWPORT[0], "height": VIEWPORT[1]},
            user_agent=self._user_agent,
            service_workers="block",
            accept_downloads=False,
            java_script_enabled=True,
        )
        archive = _ArchiveCollector(request.out_dir / "resources") if request.archive else None
        blocked_main: list[str] = []
        try:
            context.set_default_timeout(ACTION_TIMEOUT_MS)
            await context.route("**/*", _router(request, blocked_main))
            page = await context.new_page()
            if archive is not None:
                page.on("response", archive.on_response)
            try:
                await page.goto(
                    request.url, timeout=NAVIGATION_TIMEOUT_MS, wait_until="domcontentloaded"
                )
            except PlaywrightError as exc:
                if blocked_main:
                    raise SnapshotError(blocked_main[0]) from exc
                raise SnapshotError(
                    f"Page could not be loaded: {exc.message}", retryable=True
                ) from exc
            with contextlib.suppress(PlaywrightError):
                await page.wait_for_load_state("load", timeout=LOAD_STATE_TIMEOUT_MS)
            return await self._capture(page, request, archive)
        except PlaywrightError as exc:
            raise SnapshotError(f"Browser rendering failed: {exc.message}", retryable=True) from exc
        finally:
            try:
                await asyncio.wait_for(context.close(), CLOSE_TIMEOUT_SECONDS)
            except Exception:  # noqa: BLE001 - a wedged context means a wedged browser
                logger.warning("snapshot.browser.context_close_failed", exc_info=True)
                await self._shutdown()
            if archive is not None:
                await archive.cancel()

    async def _capture(
        self, page: Page, request: RenderRequest, archive: _ArchiveCollector | None
    ) -> PageCapture:
        capture = PageCapture(url=page.url)
        if archive is not None:
            capture.resources = await archive.finish()
        if request.html or request.archive:
            capture.html = await page.content()
        if request.screenshot or request.full_page:
            path = request.out_dir / "screenshot.jpg"
            height = VIEWPORT[1]
            if request.full_page:
                scroll_height = await page.evaluate(
                    "() => Math.max(document.documentElement.scrollHeight,"
                    " document.body ? document.body.scrollHeight : 0)"
                )
                height = max(VIEWPORT[1], min(int(scroll_height or 0), SCREENSHOT_MAX_HEIGHT))
            await page.screenshot(
                path=str(path),
                type="jpeg",
                quality=SCREENSHOT_QUALITY,
                full_page=request.full_page,
                clip={"x": 0, "y": 0, "width": VIEWPORT[0], "height": height},
                animations="disabled",
            )
            capture.screenshot = path
        if request.pdf:
            path = request.out_dir / "page.pdf"
            await page.pdf(path=str(path), format="A4", print_background=True)
            capture.pdf = path
        return capture


def _router(request: RenderRequest, blocked_main: list[str]) -> Any:
    """Per-request filter: only http(s), no media, and no fonts/images when nothing visual is
    captured. Destination addresses are enforced by the egress proxy (covers redirects too);
    the early host check here just fails fast with a clear reason."""
    blocked_types = {"media", "websocket", "eventsource", "manifest"}
    if not request.visual:
        blocked_types |= {"image", "font", "stylesheet"}
    verdicts: dict[tuple[str, int], str | None] = {}

    async def handle(route: PlaywrightRoute, req: Request) -> None:
        from playwright.async_api import Error as PlaywrightError

        try:
            reason = await _verdict(req, blocked_types, verdicts)
            if reason is None:
                await route.continue_()
                return
            if req.is_navigation_request() and req.frame.parent_frame is None:
                blocked_main.append(reason)
            await route.abort("blockedbyclient")
        except PlaywrightError:
            pass  # page/context already closed while the request was in flight

    return handle


async def _verdict(
    req: Request, blocked_types: set[str], cache: dict[tuple[str, int], str | None]
) -> str | None:
    if req.resource_type in blocked_types:
        return "resource type not captured"
    scheme = urlsplit(req.url).scheme
    if scheme in {"data", "blob"}:
        return None
    try:
        host, port = parse_public_url(req.url)
    except BlockedDestinationError as exc:
        return str(exc)
    if (host, port) not in cache:
        try:
            await resolve_public(host, port)
            cache[(host, port)] = None
        except BlockedDestinationError as exc:
            cache[(host, port)] = str(exc)
    return cache[(host, port)]


class _ArchiveCollector:
    """Writes whitelisted static responses (CSS, images, fonts) to disk as they arrive,
    within count and byte budgets; nothing is buffered beyond one response body."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.resources: list[ArchivedResource] = []
        self._seen: set[str] = set()
        self._tasks: set[asyncio.Task[None]] = set()
        self._total = 0
        self._counter = 0

    def on_response(self, response: Response) -> None:
        if len(self._seen) >= ARCHIVE_MAX_RESOURCES or response.url in self._seen:
            return
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type not in RESOURCE_WHITELIST or response.status != 200:
            return
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > ARCHIVE_MAX_RESOURCE_BYTES:
            return
        self._seen.add(response.url)
        task = asyncio.create_task(self._save(response, content_type))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _save(self, response: Response, content_type: str) -> None:
        from playwright.async_api import Error as PlaywrightError

        try:
            body = await response.body()
        except PlaywrightError as exc:
            logger.debug("snapshot.archive.body_unavailable", url=response.url, error=exc.message)
            return
        if not body or len(body) > ARCHIVE_MAX_RESOURCE_BYTES:
            return
        if self._total + len(body) > ARCHIVE_MAX_TOTAL_BYTES:
            return
        self._total += len(body)
        filename = f"r{self._counter:04d}{ext_for_mime(content_type)}"
        self._counter += 1
        await asyncio.to_thread((self.directory / filename).write_bytes, body)
        self.resources.append(ArchivedResource(response.url, filename, content_type))

    async def finish(self) -> list[ArchivedResource]:
        if self._tasks:
            await asyncio.wait(set(self._tasks), timeout=10)
        await self.cancel()
        return list(self.resources)

    async def cancel(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
