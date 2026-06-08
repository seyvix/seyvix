from __future__ import annotations

import importlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol

from app.core.logging import get_logger

BROWSER_VIEWPORT_WIDTH = 1280
BROWSER_VIEWPORT_HEIGHT = 800
BROWSER_TIMEOUT_MS = 20_000
BROWSER_LOAD_STATE_TIMEOUT_MS = 5_000

logger = get_logger(__name__)


class BrowserRenderError(Exception):
    pass


@dataclass(slots=True, frozen=True)
class BrowserSnapshot:
    html: str
    screenshot_bytes: bytes


@dataclass(slots=True, frozen=True)
class ArchivedResource:
    original_url: str
    filename: str
    content_type: str
    data: bytes


@dataclass(slots=True, frozen=True)
class WebArchive:
    html: str
    resources: list[ArchivedResource]


class _RenderablePage(Protocol):
    def goto(self, url: str, *, timeout: int, wait_until: str) -> object: ...

    def wait_for_load_state(self, state: str, *, timeout: int) -> object: ...


def render_url(url: str) -> BrowserSnapshot:
    """Render *url* in a headless Chromium browser.

    Runs in a dedicated thread so Playwright sync API can create its own
    event loop even when called from inside an asyncio context.
    Raises BrowserRenderError on any failure.
    """
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_render_in_thread, url).result()


def render_url_pdf(url: str) -> bytes:
    """Render *url* as a PDF via headless Chromium.

    Returns raw PDF bytes.
    Raises BrowserRenderError on any failure.
    """
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_render_pdf_in_thread, url).result()


def render_url_archive(url: str) -> WebArchive:
    """Capture rendered HTML plus static CSS/image/font resources."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_render_archive_in_thread, url).result()


def _render_archive_in_thread(url: str) -> WebArchive:
    try:
        playwright_mod = importlib.import_module("playwright.sync_api")
    except ImportError as exc:
        raise BrowserRenderError("playwright package is not installed") from exc

    from app.modules.snapshots.rewriter import RESOURCE_WHITELIST, ext_for_mime  # noqa: PLC0415

    sync_playwright = playwright_mod.sync_playwright
    resources: list[ArchivedResource] = []
    seen_urls: set[str] = set()
    counter = 0
    skipped_mime_counts: dict[str, int] = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            )
            try:
                page = browser.new_page(
                    viewport={"width": BROWSER_VIEWPORT_WIDTH, "height": BROWSER_VIEWPORT_HEIGHT},
                )

                def handle_response(response: object) -> None:
                    nonlocal counter
                    try:
                        resp_url: str = response.url  # type: ignore[attr-defined]
                        if resp_url in seen_urls:
                            return
                        content_type: str = (
                            response.headers.get("content-type", "")  # type: ignore[attr-defined]
                            .split(";")[0]
                            .strip()
                            .lower()
                        )
                        if content_type not in RESOURCE_WHITELIST:
                            skipped_key = content_type or "missing"
                            skipped_mime_counts[skipped_key] = (
                                skipped_mime_counts.get(skipped_key, 0) + 1
                            )
                            return
                        data: bytes = response.body()  # type: ignore[attr-defined]
                        if not data:
                            return
                        ext = ext_for_mime(content_type)
                        filename = f"r{counter:04d}{ext}"
                        counter += 1
                        seen_urls.add(resp_url)
                        resources.append(
                            ArchivedResource(
                                original_url=resp_url,
                                filename=filename,
                                content_type=content_type,
                                data=data,
                            )
                        )
                    except Exception:
                        return

                page.on("response", handle_response)
                logger.info("snapshot.browser.archive.goto", url=url)
                _navigate_for_render(page, url)
                html_content: str = page.content()
                logger.info(
                    "snapshot.browser.archive.complete",
                    url=url,
                    html_length=len(html_content),
                    resource_count=len(resources),
                    resource_mime_types=sorted({resource.content_type for resource in resources}),
                    skipped_mime_counts=skipped_mime_counts,
                )
                return WebArchive(html=html_content, resources=list(resources))
            finally:
                browser.close()
    except BrowserRenderError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BrowserRenderError(f"Browser archive rendering failed: {exc}") from exc


def _render_pdf_in_thread(url: str) -> bytes:
    try:
        playwright_mod = importlib.import_module("playwright.sync_api")
    except ImportError as exc:
        raise BrowserRenderError("playwright package is not installed") from exc

    sync_playwright = playwright_mod.sync_playwright
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            )
            try:
                page = browser.new_page(
                    viewport={"width": BROWSER_VIEWPORT_WIDTH, "height": BROWSER_VIEWPORT_HEIGHT},
                )
                _navigate_for_render(page, url)
                pdf_bytes: bytes = page.pdf(format="A4", print_background=True)
                return pdf_bytes
            finally:
                browser.close()
    except BrowserRenderError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BrowserRenderError(f"Browser PDF rendering failed: {exc}") from exc


def _render_in_thread(url: str) -> BrowserSnapshot:
    try:
        playwright_mod = importlib.import_module("playwright.sync_api")
    except ImportError as exc:
        raise BrowserRenderError("playwright package is not installed") from exc

    sync_playwright = playwright_mod.sync_playwright
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            )
            try:
                page = browser.new_page(
                    viewport={"width": BROWSER_VIEWPORT_WIDTH, "height": BROWSER_VIEWPORT_HEIGHT},
                )
                _navigate_for_render(page, url)
                html_content: str = page.content()
                screenshot: bytes = page.screenshot(type="jpeg", quality=85, full_page=False)
                return BrowserSnapshot(html=html_content, screenshot_bytes=screenshot)
            finally:
                browser.close()
    except BrowserRenderError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BrowserRenderError(f"Browser rendering failed: {exc}") from exc


def _navigate_for_render(page: _RenderablePage, url: str) -> None:
    page.goto(url, timeout=BROWSER_TIMEOUT_MS, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("load", timeout=BROWSER_LOAD_STATE_TIMEOUT_MS)
    except Exception as exc:  # noqa: BLE001
        logger.info("snapshot.browser.load_state_timeout", url=url, error=str(exc))
