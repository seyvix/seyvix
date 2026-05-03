
# Webpage HTML Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture full static page archives (HTML + CSS + images + fonts) and serve them through the API so `HtmlSnapshotViewer` renders visually accurate, styled snapshots.

**Architecture:** Playwright intercepts all network responses during page load, capturing whitelisted MIME types. A rewriter module rewrites URLs in HTML/CSS to point to the API and strips all JavaScript. The worker stores each resource file alongside the main artifact, and a new router endpoint serves them with correct content-types.

**Tech Stack:** Python (beautifulsoup4, existing Playwright/FastAPI), TypeScript/React (HtmlSnapshotViewer)

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `api/app/modules/snapshots/rewriter.py` | **Create** | HTML/CSS URL rewriting, JS stripping |
| `api/app/modules/snapshots/browser.py` | **Modify** | Add `ArchivedResource`, `WebArchive`, `render_url_archive()` |
| `api/app/modules/snapshots/artifacts.py` | **Modify** | Add `resources_dir` to `GeneratedArtifact`; new `_generate_browser_html_archive()` |
| `api/app/modules/snapshots/worker.py` | **Modify** | Pre-generate artifact_id; copy + store resource files |
| `api/app/platform/storage/service.py` | **Modify** | Add `StorageKeyBuilder.snapshot_artifact_resource()` and `snapshot_artifact_manifest()` |
| `api/app/modules/snapshots/service.py` | **Modify** | Add `get_artifact_resource()` |
| `api/app/modules/snapshots/presentation/rest/router.py` | **Modify** | Add `GET /artifacts/{artifact_id}/resources/{filename}` |
| `api/tests/test_rewriter.py` | **Create** | Unit tests for rewriter |
| `api/pyproject.toml` | **Modify** | Add `beautifulsoup4` dependency |
| `web/src/components/HtmlSnapshotViewer/HtmlSnapshotViewer.tsx` | **Modify** | `sandbox="allow-same-origin"` |

---

## Task 1: Add `beautifulsoup4` dependency

**Files:**
- Modify: `api/pyproject.toml`

- [ ] **Step 1: Add dependency**

In `api/pyproject.toml`, add to the `dependencies` list:
```toml
"beautifulsoup4>=4.12.0",
```

- [ ] **Step 2: Install**

```bash
cd api && uv sync
```
Expected: resolves and installs `beautifulsoup4`.

- [ ] **Step 3: Commit**

```bash
git add api/pyproject.toml api/uv.lock
git commit -m "feat: add beautifulsoup4 dependency for HTML archive rewriting"
```

---

## Task 2: Create `rewriter.py` with URL rewriting and JS stripping

**Files:**
- Create: `api/app/modules/snapshots/rewriter.py`
- Create: `api/tests/test_rewriter.py`

- [ ] **Step 1: Write failing tests**

Create `api/tests/test_rewriter.py`:

```python
from __future__ import annotations

import pytest

from app.modules.snapshots.rewriter import ext_for_mime, rewrite_css, rewrite_html


def test_rewrite_html_replaces_img_src() -> None:
    html = '<html><body><img src="https://example.com/logo.png"></body></html>'
    manifest = {"https://example.com/logo.png": "/api/v1/snapshots/artifacts/abc/resources/r0001.png"}
    result = rewrite_html(html, "https://example.com/", manifest)
    assert "/api/v1/snapshots/artifacts/abc/resources/r0001.png" in result
    assert "https://example.com/logo.png" not in result


def test_rewrite_html_resolves_relative_urls() -> None:
    html = '<html><body><img src="/images/photo.jpg"></body></html>'
    manifest = {"https://example.com/images/photo.jpg": "/api/v1/snapshots/artifacts/abc/resources/r0001.jpg"}
    result = rewrite_html(html, "https://example.com/page", manifest)
    assert "/api/v1/snapshots/artifacts/abc/resources/r0001.jpg" in result


def test_rewrite_html_strips_script_tags() -> None:
    html = '<html><body><script>alert("xss")</script><p>text</p></body></html>'
    result = rewrite_html(html, "https://example.com/", {})
    assert "alert" not in result
    assert "<script" not in result
    assert "<p>text</p>" in result


def test_rewrite_html_strips_inline_event_handlers() -> None:
    html = '<html><body><div onclick="evil()" onmouseover="bad()">click</div></body></html>'
    result = rewrite_html(html, "https://example.com/", {})
    assert "onclick" not in result
    assert "onmouseover" not in result


def test_rewrite_html_replaces_javascript_href() -> None:
    html = '<html><body><a href="javascript:void(0)">link</a></body></html>'
    result = rewrite_html(html, "https://example.com/", {})
    assert "javascript:" not in result


def test_rewrite_html_keeps_data_uris() -> None:
    html = '<html><body><img src="data:image/png;base64,abc123"></body></html>'
    result = rewrite_html(html, "https://example.com/", {})
    assert "data:image/png;base64,abc123" in result


def test_rewrite_html_rewrites_link_href_css() -> None:
    html = '<html><head><link rel="stylesheet" href="https://example.com/style.css"></head></html>'
    manifest = {"https://example.com/style.css": "/api/v1/snapshots/artifacts/abc/resources/r0001.css"}
    result = rewrite_html(html, "https://example.com/", manifest)
    assert "/api/v1/snapshots/artifacts/abc/resources/r0001.css" in result


def test_rewrite_html_rewrites_style_block_urls() -> None:
    html = '<html><head><style>body{background:url("https://example.com/bg.jpg")}</style></head></html>'
    manifest = {"https://example.com/bg.jpg": "/api/v1/snapshots/artifacts/abc/resources/r0002.jpg"}
    result = rewrite_html(html, "https://example.com/", manifest)
    assert "/api/v1/snapshots/artifacts/abc/resources/r0002.jpg" in result


def test_rewrite_html_rewrites_inline_style_urls() -> None:
    html = '<html><body><div style="background:url(https://example.com/bg.jpg)">x</div></body></html>'
    manifest = {"https://example.com/bg.jpg": "/api/v1/snapshots/artifacts/abc/resources/r0002.jpg"}
    result = rewrite_html(html, "https://example.com/", manifest)
    assert "/api/v1/snapshots/artifacts/abc/resources/r0002.jpg" in result


def test_rewrite_css_replaces_absolute_url() -> None:
    css = "body { background: url('https://example.com/bg.jpg'); }"
    manifest = {"https://example.com/bg.jpg": "/api/v1/snapshots/artifacts/abc/resources/r0002.jpg"}
    result = rewrite_css(css, "https://example.com/style.css", manifest)
    assert "/api/v1/snapshots/artifacts/abc/resources/r0002.jpg" in result


def test_rewrite_css_resolves_relative_url() -> None:
    css = "body { background: url('../images/bg.jpg'); }"
    manifest = {"https://example.com/images/bg.jpg": "/api/v1/snapshots/artifacts/abc/resources/r0002.jpg"}
    result = rewrite_css(css, "https://example.com/css/style.css", manifest)
    assert "/api/v1/snapshots/artifacts/abc/resources/r0002.jpg" in result


def test_rewrite_css_keeps_data_uris() -> None:
    css = "body { background: url('data:image/png;base64,abc'); }"
    result = rewrite_css(css, "https://example.com/style.css", {})
    assert "data:image/png;base64,abc" in result


def test_ext_for_mime_css() -> None:
    assert ext_for_mime("text/css") == ".css"


def test_ext_for_mime_strips_charset() -> None:
    assert ext_for_mime("text/css; charset=utf-8") == ".css"


def test_ext_for_mime_unknown_defaults_to_bin() -> None:
    assert ext_for_mime("application/octet-stream") == ".bin"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd api && python -m pytest tests/test_rewriter.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'app.modules.snapshots.rewriter'`

- [ ] **Step 3: Create `rewriter.py`**

Create `api/app/modules/snapshots/rewriter.py`:

```python
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
_SRC_ATTRS = {"src", "href", "data-src"}


def ext_for_mime(mime_type: str) -> str:
    """Return file extension for a MIME type, stripping charset params."""
    base = mime_type.split(";")[0].strip().lower()
    return MIME_TO_EXT.get(base, ".bin")


def _resolve(base_url: str, url: str) -> str | None:
    """Resolve a URL against a base, returning None if it should be skipped."""
    url = url.strip()
    if not url:
        return None
    lower = url.lower()
    if lower.startswith("data:") or lower.startswith("#") or lower.startswith("javascript:"):
        return None
    return urljoin(base_url, url)


def _replace_css_urls(css_text: str, base_url: str, manifest: dict[str, str]) -> str:
    """Replace url(...) references in CSS text using the manifest."""
    def replacer(m: re.Match) -> str:  # type: ignore[type-arg]
        raw = m.group(1).strip()
        # Strip surrounding quotes
        if raw and raw[0] in "\"'":
            quote = raw[0]
            raw = raw[1:-1] if raw.endswith(quote) else raw[1:]
        else:
            quote = ""
        resolved = _resolve(base_url, raw)
        if resolved and resolved in manifest:
            return f"url({quote}{manifest[resolved]}{quote})"
        return m.group(0)

    return _URL_RE.sub(replacer, css_text)


def rewrite_css(css_text: str, css_base_url: str, manifest: dict[str, str]) -> str:
    """Rewrite url() references in a CSS string using the manifest."""
    return _replace_css_urls(css_text, css_base_url, manifest)


def rewrite_html(html: str, page_url: str, manifest: dict[str, str]) -> str:
    """Rewrite resource URLs in HTML, strip all scripts and event handlers."""
    soup = BeautifulSoup(html, "html.parser")

    # Strip all <script> tags
    for tag in soup.find_all("script"):
        tag.decompose()

    # Strip on* event handlers and fix javascript: hrefs
    for tag in soup.find_all(True):
        if not isinstance(tag, Tag):
            continue
        for attr in list(tag.attrs):
            if isinstance(attr, str) and attr.lower().startswith("on"):
                del tag[attr]
        href = tag.get("href", "")
        if isinstance(href, str) and href.strip().lower().startswith("javascript:"):
            tag["href"] = "#"

    # Rewrite src/href/data-src attributes
    _TAG_ATTRS: list[tuple[str, str]] = [
        ("img", "src"), ("link", "href"), ("source", "src"),
        ("input", "src"), ("video", "src"), ("audio", "src"),
        ("embed", "src"), ("track", "src"),
    ]
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

    # Rewrite srcset attributes (format: "url size, url size, ...")
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

    # Rewrite url() in inline style attributes
    for el in soup.find_all(True, style=True):
        if not isinstance(el, Tag):
            continue
        style = el.get("style", "")
        if isinstance(style, str):
            el["style"] = _replace_css_urls(style, page_url, manifest)

    # Rewrite url() in <style> blocks
    for el in soup.find_all("style"):
        if not isinstance(el, Tag):
            continue
        if el.string:
            el.string = _replace_css_urls(el.string, page_url, manifest)

    return str(soup)
```

- [ ] **Step 4: Run tests**

```bash
cd api && python -m pytest tests/test_rewriter.py -v
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add api/app/modules/snapshots/rewriter.py api/tests/test_rewriter.py
git commit -m "feat: add HTML/CSS archive rewriter with JS stripping"
```

---

## Task 3: Add `ArchivedResource`, `WebArchive`, and `render_url_archive()` to `browser.py`

**Files:**
- Modify: `api/app/modules/snapshots/browser.py`

- [ ] **Step 1: Add dataclasses and `render_url_archive()`**

In `api/app/modules/snapshots/browser.py`, after the existing `BrowserSnapshot` dataclass, add:

```python
from app.modules.snapshots.rewriter import RESOURCE_WHITELIST, ext_for_mime


@dataclass(slots=True, frozen=True)
class ArchivedResource:
    original_url: str
    filename: str       # e.g. "r0001.css"
    content_type: str
    data: bytes


@dataclass(slots=True, frozen=True)
class WebArchive:
    html: str
    resources: list[ArchivedResource]
```

Note: the `from app.modules.snapshots.rewriter import ...` import must go inside the functions that use it (to avoid circular imports), not at module level. Add the dataclasses at module level but move the import inside the function.

After the existing `render_url_pdf` function, add:

```python
def render_url_archive(url: str) -> WebArchive:
    """Capture a full page archive: HTML + CSS, images, fonts.

    Intercepts all network responses during page load and captures resources
    matching the MIME type whitelist. Returns rewritten HTML and resources.
    Raises BrowserRenderError on any failure.
    """
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
                    except Exception:  # noqa: BLE001
                        pass  # silently skip failed captures

                page.on("response", handle_response)
                page.goto(url, timeout=BROWSER_TIMEOUT_MS, wait_until="networkidle")
                html_content: str = page.content()
                return WebArchive(html=html_content, resources=list(resources))
            finally:
                browser.close()
    except BrowserRenderError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BrowserRenderError(f"Browser archive rendering failed: {exc}") from exc
```

- [ ] **Step 2: Verify imports compile**

```bash
cd api && python -c "from app.modules.snapshots.browser import render_url_archive, WebArchive, ArchivedResource; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add api/app/modules/snapshots/browser.py
git commit -m "feat: add render_url_archive with resource interception to browser.py"
```

---

## Task 4: Extend `GeneratedArtifact` and add `_generate_browser_html_archive()` to `artifacts.py`

**Files:**
- Modify: `api/app/modules/snapshots/artifacts.py`

- [ ] **Step 1: Add `resources_dir` field to `GeneratedArtifact`**

In `api/app/modules/snapshots/artifacts.py`, find:

```python
@dataclass(slots=True)
class GeneratedArtifact:
    filename: str
    mime_type: str
    path: Path
    width: int | None = None
    height: int | None = None
```

Replace with:

```python
@dataclass(slots=True)
class GeneratedArtifact:
    filename: str
    mime_type: str
    path: Path
    width: int | None = None
    height: int | None = None
    resources_dir: Path | None = None  # set for webpage_html archives
```

- [ ] **Step 2: Update `generate()` signature to accept `artifact_id`**

Find:
```python
    def generate(
        self,
        *,
        content_object: ContentObject,
        asset: ContentAsset | None,
        job_type: str,
    ) -> GeneratedArtifact:
```

Replace with:
```python
    def generate(
        self,
        *,
        content_object: ContentObject,
        asset: ContentAsset | None,
        job_type: str,
        artifact_id: str | None = None,
    ) -> GeneratedArtifact:
```

- [ ] **Step 3: Pass `artifact_id` to `_generate_webpage_html` in `generate()`**

Find:
```python
        if job_type == "webpage_html":
            return self._generate_webpage_html(
                asset=asset, source_path=source_path, output_dir=output_dir
            )
```

Replace with:
```python
        if job_type == "webpage_html":
            return self._generate_webpage_html(
                asset=asset, source_path=source_path, output_dir=output_dir,
                artifact_id=artifact_id,
            )
```

- [ ] **Step 4: Update `_generate_webpage_html` signature and routing**

Find:
```python
    def _generate_webpage_html(
        self,
        *,
        asset: ContentAsset,
        source_path: Path,
        output_dir: Path,
    ) -> GeneratedArtifact:
        suffix = source_path.suffix.lower()
        path = output_dir / "snapshot.html"
        if asset.media_type == "link":
            return self._generate_browser_html(
                asset=asset, source_path=source_path, output_dir=output_dir
            )
```

Replace with:
```python
    def _generate_webpage_html(
        self,
        *,
        asset: ContentAsset,
        source_path: Path,
        output_dir: Path,
        artifact_id: str | None = None,
    ) -> GeneratedArtifact:
        suffix = source_path.suffix.lower()
        path = output_dir / "snapshot.html"
        if asset.media_type == "link":
            if artifact_id is not None:
                return self._generate_browser_html_archive(
                    asset=asset, source_path=source_path, output_dir=output_dir,
                    artifact_id=artifact_id,
                )
            return self._generate_browser_html(
                asset=asset, source_path=source_path, output_dir=output_dir
            )
```

- [ ] **Step 5: Add `_generate_browser_html_archive()` method**

Add the following method to `SnapshotArtifactGenerator`, after `_generate_browser_html`:

```python
    def _generate_browser_html_archive(
        self,
        *,
        asset: ContentAsset,
        source_path: Path,
        output_dir: Path,
        artifact_id: str,
    ) -> GeneratedArtifact:
        import json  # noqa: PLC0415

        from app.core.config import get_settings  # noqa: PLC0415
        from app.modules.snapshots.browser import BrowserRenderError, render_url_archive  # noqa: PLC0415
        from app.modules.snapshots.rewriter import rewrite_css, rewrite_html  # noqa: PLC0415

        url = self._link_url(asset=asset, source_path=source_path)
        try:
            archive = render_url_archive(url)
        except BrowserRenderError as exc:
            raise UnsupportedSnapshotError(str(exc)) from exc

        api_prefix = get_settings().api_prefix

        # Build manifest: original_url → API path
        manifest: dict[str, str] = {
            resource.original_url: (
                f"{api_prefix}/snapshots/artifacts/{artifact_id}/resources/{resource.filename}"
            )
            for resource in archive.resources
        }

        # Rewrite HTML
        rewritten_html = rewrite_html(archive.html, url, manifest)
        index_path = output_dir / "snapshot.html"
        index_path.write_text(rewritten_html, encoding="utf-8")

        # Write resources and build content-type manifest
        resources_dir = output_dir / "resources"
        resources_dir.mkdir(exist_ok=True)
        content_type_map: dict[str, str] = {}

        for resource in archive.resources:
            resource_path = resources_dir / resource.filename
            if resource.content_type == "text/css":
                rewritten = rewrite_css(
                    resource.data.decode("utf-8", errors="replace"),
                    resource.original_url,
                    manifest,
                )
                resource_path.write_bytes(rewritten.encode("utf-8"))
            else:
                resource_path.write_bytes(resource.data)
            content_type_map[resource.filename] = resource.content_type

        # Write manifest.json
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(json.dumps(content_type_map), encoding="utf-8")

        return GeneratedArtifact(
            filename="snapshot.html",
            mime_type="text/html",
            path=index_path,
            resources_dir=resources_dir,
        )
```

- [ ] **Step 6: Verify imports compile**

```bash
cd api && python -c "from app.modules.snapshots.artifacts import SnapshotArtifactGenerator, GeneratedArtifact; print('OK')"
```
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add api/app/modules/snapshots/artifacts.py
git commit -m "feat: add _generate_browser_html_archive using resource interception and URL rewriting"
```

---

## Task 5: Add `snapshot_artifact_resource` and `snapshot_artifact_manifest` to `StorageKeyBuilder`

**Files:**
- Modify: `api/app/platform/storage/service.py`

- [ ] **Step 1: Add the two new static methods**

In `api/app/platform/storage/service.py`, after `snapshot_artifact()`, add:

```python
    @staticmethod
    def snapshot_artifact_resource(
        *,
        content_object_id: str,
        snapshot_id: str,
        filename: str,
    ) -> str:
        return f"snapshots/{content_object_id}/{snapshot_id}/resources/{_safe_file_name(filename)}"

    @staticmethod
    def snapshot_artifact_manifest(
        *,
        content_object_id: str,
        snapshot_id: str,
    ) -> str:
        return f"snapshots/{content_object_id}/{snapshot_id}/manifest.json"
```

- [ ] **Step 2: Verify**

```bash
cd api && python -c "from app.platform.storage.service import StorageKeyBuilder; print(StorageKeyBuilder.snapshot_artifact_resource(content_object_id='x', snapshot_id='y', filename='r0001.css'))"
```
Expected: `snapshots/x/y/resources/r0001.css`

- [ ] **Step 3: Commit**

```bash
git add api/app/platform/storage/service.py
git commit -m "feat: add snapshot_artifact_resource and snapshot_artifact_manifest key builders"
```

---

## Task 6: Extend `worker.py` to pre-generate artifact_id and store resources

**Files:**
- Modify: `api/app/modules/snapshots/worker.py`

- [ ] **Step 1: Add missing imports to `worker.py`**

At the top of `api/app/modules/snapshots/worker.py`, add:

```python
import shutil
from uuid import uuid4
```

(Add to the existing import block at the top of the file.)

- [ ] **Step 2: Update `_generate_with_storage` signature and resource copying**

Find the `_generate_with_storage` method. Replace it entirely with:

```python
    def _generate_with_storage(
        self,
        *,
        content_object: ContentObject,
        asset: ContentAsset | None,
        job: SnapshotJob,
        artifact_id: str | None = None,
    ) -> GeneratedArtifact:
        if asset is None:
            generator = SnapshotArtifactGenerator(self.storage_root)
            return generator.generate(
                content_object=content_object, asset=asset, job_type=job.job_type,
                artifact_id=artifact_id,
            )

        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_key = asset.storage_key or asset.storage_path
            source_path = temp_root / source_key
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_bytes(self.storage_backend.get_bytes(source_key))

            local_content_object = copy.copy(content_object)
            local_content_object.storage_path = f"content-assets/{content_object.id}"
            local_asset = copy.copy(asset)
            local_asset.storage_path = source_key

            generator = SnapshotArtifactGenerator(temp_root)
            generated = generator.generate(
                content_object=local_content_object,
                asset=local_asset,
                job_type=job.job_type,
                artifact_id=artifact_id,
            )
            stable_path = self.storage_root / ".snapshot-worker" / job.id / generated.filename
            stable_path.parent.mkdir(parents=True, exist_ok=True)
            stable_path.write_bytes(generated.path.read_bytes())

            # Copy web archive resources out of temp dir before it is deleted
            stable_resources_dir: Path | None = None
            if generated.resources_dir is not None and generated.resources_dir.exists():
                stable_resources_dir = stable_path.parent / "resources"
                shutil.copytree(generated.resources_dir, stable_resources_dir)
                manifest_src = generated.resources_dir.parent / "manifest.json"
                if manifest_src.exists():
                    shutil.copy2(manifest_src, stable_path.parent / "manifest.json")

            return GeneratedArtifact(
                filename=generated.filename,
                mime_type=generated.mime_type,
                path=stable_path,
                width=generated.width,
                height=generated.height,
                resources_dir=stable_resources_dir,
            )
```

- [ ] **Step 3: Update `_process_job` to pre-generate artifact_id and store resources**

In `_process_job`, find:

```python
        content_object = await self.content.get_object(job.content_object_id)
        asset = await self.content.get_asset(job.source_asset_id) if job.source_asset_id else None
        if content_object is None:
            self._fail_job(job, "Content object not found.")
            return

        try:
            generated = self._generate_with_storage(
                content_object=content_object,
                asset=asset,
                job=job,
            )
```

Replace with:

```python
        content_object = await self.content.get_object(job.content_object_id)
        asset = await self.content.get_asset(job.source_asset_id) if job.source_asset_id else None
        if content_object is None:
            self._fail_job(job, "Content object not found.")
            return

        # Pre-generate artifact ID for web archives so resource URLs can be embedded during generation
        pregenerated_artifact_id: str | None = None
        if job.job_type == "webpage_html" and asset is not None and asset.media_type == "link":
            pregenerated_artifact_id = str(uuid4())

        try:
            generated = self._generate_with_storage(
                content_object=content_object,
                asset=asset,
                job=job,
                artifact_id=pregenerated_artifact_id,
            )
```

Then find the artifact creation block:

```python
        artifact = SnapshotArtifact(
            owner_user_id=job.owner_user_id,
            content_object_id=job.content_object_id,
            source_asset_id=job.source_asset_id,
            artifact_type=job.job_type,
            filename=generated.filename,
            mime_type=generated.mime_type,
            size_bytes=stored.size_bytes,
            storage_path=stored.storage_key,
            storage_backend=stored.storage_backend,
            bucket=stored.bucket,
            storage_key=stored.storage_key,
            storage_ref=stored.storage_ref,
            checksum=stored.checksum,
            status="ready",
        )
        self.artifacts.add(artifact)
```

Replace with:

```python
        # Store web archive resources (CSS, images, fonts) if present
        if generated.resources_dir is not None and generated.resources_dir.exists():
            manifest_file = generated.resources_dir.parent / "manifest.json"
            if manifest_file.exists():
                self.storage_backend.put_bytes(
                    storage_key=StorageKeyBuilder.snapshot_artifact_manifest(
                        content_object_id=job.content_object_id,
                        snapshot_id=job.id,
                    ),
                    data=manifest_file.read_bytes(),
                    content_type="application/json",
                )
            for resource_file in sorted(generated.resources_dir.iterdir()):
                if resource_file.is_file():
                    self.storage_backend.put_bytes(
                        storage_key=StorageKeyBuilder.snapshot_artifact_resource(
                            content_object_id=job.content_object_id,
                            snapshot_id=job.id,
                            filename=resource_file.name,
                        ),
                        data=resource_file.read_bytes(),
                        content_type=None,
                    )

        artifact = SnapshotArtifact(
            id=pregenerated_artifact_id or str(uuid4()),
            owner_user_id=job.owner_user_id,
            content_object_id=job.content_object_id,
            source_asset_id=job.source_asset_id,
            artifact_type=job.job_type,
            filename=generated.filename,
            mime_type=generated.mime_type,
            size_bytes=stored.size_bytes,
            storage_path=stored.storage_key,
            storage_backend=stored.storage_backend,
            bucket=stored.bucket,
            storage_key=stored.storage_key,
            storage_ref=stored.storage_ref,
            checksum=stored.checksum,
            status="ready",
        )
        self.artifacts.add(artifact)
```

Also add `StorageKeyBuilder` to the imports at the top of worker.py. Find:

```python
from app.platform.storage.service import LocalVolumeStorage, StorageBackend, StorageKeyBuilder
```

It is already imported. ✓

- [ ] **Step 4: Verify imports compile**

```bash
cd api && python -c "from app.modules.snapshots.worker import SnapshotWorker; print('OK')"
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add api/app/modules/snapshots/worker.py
git commit -m "feat: pre-generate artifact_id and store web archive resources in worker"
```

---

## Task 7: Add `get_artifact_resource()` to `SnapshotService`

**Files:**
- Modify: `api/app/modules/snapshots/service.py`

- [ ] **Step 1: Add `json` import**

At the top of `api/app/modules/snapshots/service.py`, add `import json` to the imports.

- [ ] **Step 2: Add the method**

After `get_thumbnail_text()`, add:

```python
    async def get_artifact_resource(
        self,
        *,
        owner_user_id: str,
        artifact_id: str,
        filename: str,
    ) -> tuple[bytes, str]:
        """Return (bytes, content_type) for a web archive resource file."""
        artifact = await self.artifacts.get_for_user(
            owner_user_id=owner_user_id,
            artifact_id=artifact_id,
        )
        if artifact is None:
            raise SnapshotArtifactNotFoundError

        # Derive directory prefix from storage_key:
        # "snapshots/{content_object_id}/{job_id}/snapshot.html"
        # → "snapshots/{content_object_id}/{job_id}"
        storage_key = artifact.storage_key or artifact.storage_path
        prefix = storage_key.rsplit("/", 1)[0]

        manifest_key = f"{prefix}/manifest.json"
        try:
            manifest_bytes = self.storage_backend.get_bytes(manifest_key)
            content_type_map: dict[str, str] = json.loads(manifest_bytes)
        except Exception as exc:  # noqa: BLE001
            raise SnapshotArtifactNotFoundError from exc

        content_type = content_type_map.get(filename, "application/octet-stream")

        resource_key = f"{prefix}/resources/{filename}"
        try:
            data = self.storage_backend.get_bytes(resource_key)
        except Exception as exc:  # noqa: BLE001
            raise SnapshotArtifactNotFoundError from exc

        return data, content_type
```

- [ ] **Step 3: Verify**

```bash
cd api && python -c "from app.modules.snapshots.service import SnapshotService; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add api/app/modules/snapshots/service.py
git commit -m "feat: add get_artifact_resource to SnapshotService"
```

---

## Task 8: Add resource endpoint to snapshot router

**Files:**
- Modify: `api/app/modules/snapshots/presentation/rest/router.py`

- [ ] **Step 1: Add `Response` to FastAPI imports**

Find:
```python
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
```

Replace with:
```python
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, Response
```

- [ ] **Step 2: Add the endpoint**

At the end of `router.py`, add:

```python
@router.get(
    "/artifacts/{artifact_id}/resources/{filename}",
    summary="Get snapshot archive resource",
    description=(
        "Streams a static resource file (CSS, image, font) belonging to a webpage HTML archive. "
        "Only accessible to the artifact owner."
    ),
    responses={
        200: {"description": "Resource file returned."},
        401: {"model": ErrorResponse, "description": "Missing or invalid access token."},
        404: {"model": ErrorResponse, "description": "Resource not found."},
    },
)
async def get_snapshot_artifact_resource(
    artifact_id: str,
    filename: str,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SnapshotService, Depends(get_snapshot_service)],
) -> Response:
    try:
        data, content_type = await service.get_artifact_resource(
            owner_user_id=context.user.id,
            artifact_id=artifact_id,
            filename=filename,
        )
    except SnapshotArtifactNotFoundError as exc:
        raise AppError(
            status_code=404,
            code="snapshot_artifact_not_found",
            message="Snapshot artifact not found.",
        ) from exc
    return Response(content=data, media_type=content_type)
```

- [ ] **Step 3: Verify app starts**

```bash
cd api && python -c "from app.modules.snapshots.presentation.rest.router import router; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add api/app/modules/snapshots/presentation/rest/router.py
git commit -m "feat: add GET /snapshots/artifacts/{id}/resources/{filename} endpoint"
```

---

## Task 9: Update `HtmlSnapshotViewer` sandbox attribute

**Files:**
- Modify: `web/src/components/HtmlSnapshotViewer/HtmlSnapshotViewer.tsx`

- [ ] **Step 1: Change sandbox attribute**

Find:
```tsx
      sandbox=""
```

Replace with:
```tsx
      sandbox="allow-same-origin"
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd web && npx tsc --noEmit 2>&1 | head -20
```
Expected: no output (no errors).

- [ ] **Step 3: Commit**

```bash
git add web/src/components/HtmlSnapshotViewer/HtmlSnapshotViewer.tsx
git commit -m "fix: allow-same-origin sandbox in HtmlSnapshotViewer for resource loading"
```

---

## Task 10: Run full test suite

- [ ] **Step 1: Run existing snapshot tests**

```bash
cd api && python -m pytest tests/test_snapshots.py tests/test_rewriter.py -v
```
Expected: all pass.

- [ ] **Step 2: Run full test suite**

```bash
cd api && python -m pytest -x -q
```
Expected: all tests pass.

- [ ] **Step 3: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "fix: resolve any issues from full test suite run"
```
