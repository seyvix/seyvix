# Webpage HTML Archive (Wayback Machine-style) Design

**Date:** 2026-05-03
**Status:** Approved

## Problem

The current `webpage_html` snapshot captures only `page.content()` (the rendered DOM HTML). Relative URLs for images, CSS, and fonts break when the HTML is loaded as a blob URL in an iframe. The result is an unstyled, broken-looking snapshot.

## Goal

Capture the full static page archive (HTML + CSS + images + fonts, no JS) and serve each resource through the API. The iframe receives correctly styled, visually accurate snapshots.

---

## Architecture

### 1. Capture — `browser.py`

New function `render_url_archive(url: str) -> WebArchive` (runs in `ThreadPoolExecutor` like existing functions).

Uses `page.route("**/*")` to intercept all network responses during page load. For each response, if the content-type is in the whitelist, save bytes + metadata.

**Resource whitelist (MIME types):**
- `text/css`
- `image/jpeg`, `image/png`, `image/gif`, `image/webp`, `image/svg+xml`, `image/x-icon`, `image/vnd.microsoft.icon`
- `font/woff`, `font/woff2`, `font/ttf`, `font/otf`
- `application/font-woff`, `application/font-woff2`, `application/x-font-ttf`

JS, XHR, WebSocket, and other types are ignored (not captured, not blocked — page still loads normally).

```python
@dataclass
class ArchivedResource:
    original_url: str
    filename: str       # "r0001.css", "r0002.jpg" — sequential index + original ext
    content_type: str
    data: bytes

@dataclass
class WebArchive:
    html: str                        # URL-rewritten, JS-stripped HTML
    resources: list[ArchivedResource]
```

After `page.goto(url, wait_until="networkidle")`, call `page.content()` for the HTML.

### 2. HTML/CSS Rewriting — `rewriter.py` (new file)

Two-pass algorithm:

**Pass 1 — Build manifest:**
```
manifest: dict[original_url, api_path]
  e.g. "https://example.com/static/logo.png"
    → "/api/v1/snapshots/artifacts/{artifact_id}/resources/r0002.png"
```
Filenames are assigned sequentially (`r{index:04d}{ext}`). Extension derived from content-type.

**Pass 2 — Rewrite HTML:**
Using BeautifulSoup:
- Replace `src`, `href`, `data-src` attribute values: resolve relative → absolute using page URL as base, look up in manifest, replace with API path
- Replace `url(...)` in inline `style` attributes and `<style>` blocks via regex
- **Remove all `<script>` tags** (including inline and external)
- **Remove all `on*` event handler attributes** (`onclick`, `onload`, `onerror`, etc.)
- **Remove `javascript:` href values** (replace with `#`)

**Pass 2 — Rewrite CSS:**
For each captured CSS resource, apply regex `url(...)` rewriting:
- Resolve relative URL using the CSS file's own `original_url` as base
- Look up resolved URL in manifest, replace with API path
- Store rewritten CSS bytes back into `ArchivedResource.data`

URL resolution rules (for both HTML and CSS):
- Skip `data:` URIs (already inlined)
- Skip `#fragment` URLs
- Skip `javascript:` URLs (remove/replace)
- All others: `urljoin(base_url, url)`

### 3. Storage

Each resource stored as a separate file in the storage backend:

```
snapshots/{artifact_id}/index.html           ← SnapshotArtifact.storage_path
snapshots/{artifact_id}/resources/r0001.css
snapshots/{artifact_id}/resources/r0002.jpg
snapshots/{artifact_id}/resources/r0003.woff2
```

`SnapshotArtifact` record:
- `artifact_type = "webpage_html"`
- `storage_path = "snapshots/{artifact_id}/index.html"`
- `mime_type = "text/html"`
- `filename = "snapshot.html"`

Resources are not represented as separate DB records — derived from `artifact_id` at serve time.

### 4. Generation — `artifacts.py`

New method `_generate_webpage_html_archive(asset, output_dir)` replaces the existing `webpage_html` generation path:

1. Create `SnapshotArtifact` record → obtain `artifact_id`
2. Call `render_url_archive(url)` → `WebArchive`
3. Build manifest using `artifact_id` (API paths are now known)
4. Call `rewrite_html(html, manifest, page_url)` → rewritten HTML string
5. Call `rewrite_css(resource, manifest)` for each CSS resource
6. Store `index.html` via storage backend at `snapshots/{artifact_id}/index.html`
7. Store each resource at `snapshots/{artifact_id}/resources/{filename}`
8. Update artifact record: `status = "ready"`, `size_bytes = len(index_html)`

### 5. New API Endpoint

```
GET /api/v1/snapshots/artifacts/{artifact_id}/resources/{filename}
```

- Validates that `artifact_id` belongs to authenticated user (via existing `SnapshotArtifactRepository`)
- Resolves storage path: `snapshots/{artifact_id}/resources/{filename}`
- Streams file bytes with correct `Content-Type` header
- Returns 404 if artifact or resource not found

Added to existing snapshot router.

### 6. `service.py`

New method `get_artifact_resource(owner_user_id, artifact_id, filename) -> tuple[bytes, str]`:
- Checks artifact ownership
- Reads resource from storage
- Returns `(bytes, content_type)`

Content-type stored in a sidecar manifest JSON at `snapshots/{artifact_id}/manifest.json`:
```json
{"r0001.css": "text/css", "r0002.jpg": "image/jpeg", ...}
```
Loaded once per request, lightweight.

---

## Frontend

`HtmlSnapshotViewer.tsx` — single change:

```diff
- sandbox=""
+ sandbox="allow-same-origin"
```

The loaded HTML has absolute `/api/v1/...` paths for all resources. The browser fetches them automatically from the iframe context. Since the app uses session cookies and the iframe is same-origin (`allow-same-origin`), auth is included automatically.

No other frontend changes needed.

---

## Scope

**In scope:**
- `webpage_html` artifact type only
- CSS, image, font resources
- HTML and CSS URL rewriting
- JS and event handler stripping
- New `resources/{filename}` endpoint

**Out of scope:**
- JS capture and execution
- iframe-embedded sub-pages
- Existing `thumbnail`, `markdown`, `pdf` artifact types
- Retroactive re-archiving of existing snapshots

---

## Error Handling

- If `render_url_archive` fails → fall back to `page.content()` only (existing behavior), mark artifact as degraded
- If a resource fetch fails during interception → skip it silently (page may render with some assets missing)
- Resource not found in storage → 404 (don't expose internal paths)
