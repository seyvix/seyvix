from __future__ import annotations

import importlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

BROWSER_VIEWPORT_WIDTH = 1280
BROWSER_VIEWPORT_HEIGHT = 800
BROWSER_TIMEOUT_MS = 20_000


class BrowserRenderError(Exception):
    pass


@dataclass(slots=True, frozen=True)
class BrowserSnapshot:
    html: str
    screenshot_bytes: bytes


def render_url(url: str) -> BrowserSnapshot:
    """Render *url* in a headless Chromium browser.

    Runs in a dedicated thread so Playwright sync API can create its own
    event loop even when called from inside an asyncio context.
    Raises BrowserRenderError on any failure.
    """
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_render_in_thread, url).result()


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
                page.goto(url, timeout=BROWSER_TIMEOUT_MS, wait_until="networkidle")
                html_content: str = page.content()
                screenshot: bytes = page.screenshot(type="jpeg", quality=85, full_page=False)
                return BrowserSnapshot(html=html_content, screenshot_bytes=screenshot)
            finally:
                browser.close()
    except BrowserRenderError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BrowserRenderError(f"Browser rendering failed: {exc}") from exc
