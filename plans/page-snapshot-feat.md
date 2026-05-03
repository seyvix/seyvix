# Link Snapshots Implementation Plan

Goal: добавить создание composite notes из текста со ссылками, архивирование ссылок через Playwright/Chromium snapshot worker и отображение link snapshots во frontend viewer.

Architecture:
Backend владеет правилами извлечения ссылок, создания assets, snapshot jobs и форматом отображения. Frontend не решает бизнес-логику, а только рендерит `Note.objects/assets`, `snapshotViews` и вызывает backend actions. Link snapshot immutable: это снимок страницы в момент создания, обновлений snapshot не предполагается.

Important constraints:
- Не превращать несколько ссылок в collection. Несколько ссылок в одной заметке = одна composite note с несколькими `link` assets.
- Если заметка состоит только из ссылок, не создавать отдельный text asset.
- Если помимо ссылок есть текст, создать text asset с остаточным текстом + link assets.
- Thumbnail для link делать через Playwright/Chromium worker.
- Link snapshot = архив, не live preview.
- Этап 1: link extraction + archive viewer.
- Этап 2: annotations/highlights over immutable archived DOM.

## Current Code Context

Relevant backend files:
- `api/app/modules/content/service.py`
  - already has `_create_link_note()`
  - already stores single link as `ContentAsset(media_type="link")`
  - currently only detects pure single URL via `_plain_url(text)`
- `api/app/modules/content/schemas.py`
  - `NoteAssetResponse` already includes snapshot urls and asset fields
- `api/app/modules/snapshots/service.py`
  - `plan_snapshot_job_types()`
  - `_is_site_asset(asset)` already treats `media_type == "link"` as site asset
- `api/app/modules/snapshots/artifacts.py`
  - currently has `_generate_webpage_html()`, `_generate_screenshot()`, `_fetch_webpage()`
  - screenshot for link is currently text-ish fallback, should become browser screenshot
- `api/app/modules/snapshots/worker.py`
  - executes snapshot jobs and stores artifacts

Relevant frontend files:
- `web/src/api/notes.ts`
  - maps backend assets to `NoteObject`
- `web/src/types/index.ts`
  - `NoteObject`, `SnapshotView`
- `web/src/pages/NotePage.tsx`
  - currently renders documents via `PDFViewer`
  - currently link object renders a fake iframe preview
- `web/src/components/PDFViewer/PDFViewer.tsx`
  - current PDF-only iframe component
- create new `web/src/components/HtmlSnapshotViewer/HtmlSnapshotViewer.tsx`

## Stage 1: Link Assets + Archive Viewer

### Task 1: Extract links from created text notes

Modify `api/app/modules/content/service.py`.

Add a helper that:
- finds URL candidates with regex;
- validates/normalizes each candidate through `urllib.parse.urlparse`;
- removes duplicates preserving order;
- returns `(links, remaining_text)`.

Rules:
- accept `http://` and `https://`;
- reject URLs without hostname;
- strip trailing punctuation like `.`, `,`, `)`, `]` only when it is not part of URL;
- remaining text is original text with URL spans removed, whitespace normalized.

Suggested helpers:
- `_extract_links_from_text(text: str) -> tuple[list[str], str]`
- `_normalize_url_candidate(candidate: str) -> str | None`

### Task 2: Generalize note creation for text containing links

Modify `ContentService.create_note()` in `api/app/modules/content/service.py`.

Current behavior:
- pure single URL calls `_create_link_note()`;
- otherwise creates text note.

New behavior:
- when `media_type in (None, "text", "link") and text is not None`, call `_extract_links_from_text(text)`.
- if links exist:
  - if `remaining_text` is empty and `len(links) == 1`, existing `_create_link_note()` path is OK.
  - otherwise call a new helper `_create_note_from_text_and_links(...)`.
- if no links, keep existing text/link behavior.

Create helper:
- `_create_note_from_text_and_links(owner_user_id, text, links, title, folder_path, tag_names) -> NoteCardResponse`

Behavior:
- creates one `ContentObject`;
- `kind = "complex"` if multiple assets;
- `media_type = "link"` when only links, otherwise likely `"text"` or `None` depending existing conventions;
- creates a `text` asset only if remaining text is non-empty;
- creates one `link` asset per URL:
  - `media_type="link"`
  - `mime_type="text/uri-list"`
  - `filename` like `link-1.url`
  - `text_content=url`
  - storage body is `url + "\n"`
- after commit, call existing reload/write manifest path so snapshots enqueue like other objects.

### Task 3: Ensure snapshot jobs enqueue for every link asset

Check `SnapshotService.enqueue_for_content_object()` in `api/app/modules/snapshots/service.py`.

Expected:
- it iterates original assets;
- `plan_snapshot_job_types(asset, effective)` should include `thumbnail`, `screenshot`, `webpage_html`, `markdown`, maybe `pdf` for every `link` asset.

If current settings disable some formats by default, keep behavior setting-driven. Do not hardcode all jobs unless project requirements say snapshots must always archive links.

### Task 4: Add Playwright/Chromium rendering backend

Add a focused browser rendering helper/module, for example:

- `api/app/modules/snapshots/browser.py`

Responsibilities:
- launch Chromium/Playwright;
- fetch/render URL;
- return:
  - rendered HTML: `page.content()`
  - screenshot bytes
  - optional title/final_url metadata later

Prefer async if worker supports it; otherwise keep worker integration simple and isolated.

Need dependency/container decision:
- add Playwright Python dependency;
- ensure Chromium is installed in worker image/container;
- add timeout limits, max page load time, viewport size;
- block dangerous/private network URLs if not already handled.

Important security guard:
- reject localhost/private IP URLs, metadata IPs, internal hosts. Existing `_fetch_webpage()` has some SSRF-related imports; reuse or centralize this validation.

### Task 5: Use Playwright for link thumbnail/screenshot/html

Modify `api/app/modules/snapshots/artifacts.py`.

For `asset.media_type == "link"`:
- `_generate_thumbnail()` should create thumbnail from browser screenshot, not text thumbnail.
- `_generate_screenshot()` should create screenshot artifact from browser screenshot.
- `_generate_webpage_html()` should store rendered `page.content()`.

Keep original HTML artifact immutable. Do not implement annotations in this stage.

Artifact naming:
- thumbnail: `thumbnail.jpg`
- screenshot: `screenshot.jpg` or `screenshot.png`
- html: `snapshot.html`

### Task 6: Frontend HTML snapshot viewer

Create:
- `web/src/components/HtmlSnapshotViewer/HtmlSnapshotViewer.tsx`
- `web/src/components/HtmlSnapshotViewer/HtmlSnapshotViewer.module.css`

Behavior:
- accepts artifact URL;
- fetches through `apiFetch`;
- creates Blob URL or uses `srcDoc`;
- renders in sandboxed iframe;
- default sandbox should not allow scripts.
- cleanup object URL on unmount.

Recommended iframe:
- `sandbox=""` if possible;
- if styles/resources require it, use minimum necessary permissions;
- avoid `allow-scripts` for Stage 1.

### Task 7: Use HTML viewer for link objects on note page

Modify `web/src/pages/NotePage.tsx`.

For `NoteObject.type === "link"`:
- find `webpage_html` snapshot view;
- if present, show “Open snapshot” or inline `HtmlSnapshotViewer`;
- still show external original URL action separately;
- while snapshot is pending, show current link preview/pending state.

Frontend should not decide whether link should have snapshot; it only reads `snapshotViews`.

## Stage 2: Annotations Over Immutable Snapshot

### Task 8: Add annotation model/API

Backend should store user actions separately from original snapshot.

Potential model:
- `SnapshotAnnotation`
  - `id`
  - `owner_user_id`
  - `artifact_id`
  - `annotation_type`: `text_highlight` | `element_box`
  - `selector` or DOM path
  - `start_offset`, `end_offset` for text ranges if needed
  - `text_quote`
  - `color`
  - `metadata`
  - timestamps

API:
- list annotations for artifact
- create annotation
- delete annotation

### Task 9: Add backend materialization

Backend takes original/annotated HTML + annotation action and returns updated view.

Options:
- MVP: store annotations separately, frontend overlays them in iframe.
- Preferred long-term: backend materializes `annotated_html` artifact/cache after each annotation.

Since requirement says backend owns rendering rules, prefer backend materialization.

### Task 10: Add viewer selection tools

Frontend `HtmlSnapshotViewer`:
- user selects text or clicks DOM element in iframe;
- frontend sends minimal payload to backend;
- backend validates and applies annotation;
- frontend reloads returned annotated HTML.

No snapshot update semantics: original remains unchanged, annotated artifact evolves.

## Acceptance Criteria

Stage 1:
- Creating note with `https://a.com https://b.com` creates one note with two link assets and no text asset.
- Creating note with `read this https://a.com` creates one note with text asset plus one link asset.
- Each link asset receives snapshot jobs.
- Link thumbnail is generated from Chromium screenshot.
- Detail page can show archived HTML snapshot in sandboxed viewer.
- Original link can still be opened externally.

Stage 2:
- User can highlight text in archived HTML.
- User can draw/mark a DOM element box.
- Original archived HTML is preserved.
- Annotated view is derived from backend-owned rules.

## Favicons

При создании записи нужно в центре cover сразу отображать favicon получаемый путем изложенным ниже, далее уже по готовности меняй на thumbnail

запросы такие делай:
https://favicon.yandex.net/favicon/v2/<url>?json=1&allsizes=1
например:
https://favicon.yandex.net/favicon/v2/https://yandex.ru?json=1&allsizes=1
пример возвращаемого результата:
[
  {
    "16": {
      "original_height": 16,
      "image": "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAABeklEQVR4AYyTA6wdQRiFv5nabqPaRtiotjZ2qlh1GxZBbdsOattRzaAOavd5Z97+e61591vjP+eMFGkUThjdvxJ2nMF6QCsABY9APTJUWVBj9/F3JBEXsBO8+sWUzgM7FSdqdbVASO0+/gtAx4pLKLlWcTHIP/Kv1MQFxNlCr7hH42ZUmbOYqhuOUm3XGTmC50XEkH+lBqBy4QSvFZQknGvWCovB4h8/gP34hsqTp2dNEvTXico6dE+gO3ZHNW5K2fZV+Hcu40JhPB2PHqNWbQRb8I88GKfBJgtgHtxDqDTUIw9aadIp+I9/aCu6U3eqLtsZdqgLDbwjjbKLJ8IkUix94uCRNnCCNMLCPn3xb192dqQSAYU+ThoyjPbbZ/wTB3FhMAt0jd2nrxtYE1dt0Qbz6on0QygimId3g3dPSWNNjd3n36mkdXAtbUSc0atSdYCsBw0gN9WoMiCexM2aWDFAluU8vBWo+QrdMynRO+CERR+XJpNEuQADABM/mZ3+2HVaAAAAAElFTkSuQmCC",
      "original_width": 16
    },
    "32": {
      "original_height": 32,
      "image": "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAC1ElEQVR4AcSXAWSUbxzHP7/nbrf//oVhGjCvQoPVCoRYozKhW4AKOxCQFpjAbqCCtgFMccMWYDdIFDVKgbUEgbwCSjhUtdu9z9P709142N29d/fShxfneL6/3/f5Pb/n9wgJcYXpwd9Upw0yAW7cIQG4QVCkIrgQZMfitv4jV5ZSuUIChDb8KkwHGfZuWSigggkRpGTpWxgolcOuAtCMd9mbBzdLT8hSfxxIM0ekWdZC9QUQkA6hIzd5kBsGfL4XLo2nLK4EumY1XrtlAJp5FjZQ8fQJLGyohrcF/p5X37UTl+NjZE6fwYyegKFh5P9D+ECtvEa0uU4Twn5ypxo1kaWOFlw78ezVG2Qu5umRoK51G8A0rNdq70Tc/fxBtP2G6NVz/fQ3SVEt1dx3wMQROZojQ8OeePQ6Fl1f8UT7dDtGx0iKUNWEZ7P1vS/QgsyFyzRw375Qe7hIrwjMxNpFo+2VNsjIMRrY2PY0cPC3tWtv5x9hYMI4GKc1arvvRkqotknSdNznTzQwcaFpUaaBQGAS3HBa9X7Fz93VIFKpA0MSYvHaowfesdQg9Nj1igGpkAC7/TYOYtELIjd3j0zcoLQdd4NAxQAhCdGOV52/6W2H3gvd4iA0DvueDpCRo17G6ooG1A0COwbkJQlR27P56zSInpWxHz/QLRa2jA6QSesgk7+GDB3Z7w1ReZ1eUG2j97LFrdIGc/Y8mfhrsHf/TtfWKwIl1TYAgl3qxPra5hrqQC9Y7AKAARgoPQ0tLNMEPWopWq8sq6Y3EQ2QK+5SzXutWYkr3sbFpp/fln2ixytEejrQIL+itBjJitQRfyidCgTjTcQpEzrspGZ/4FSsf9TgChCSPqGurRot3wWHS092NEogTDtzXbvFu8B3QkdnLUx6Z1nX0jW7fJxOBSBFQWZIjFTArTrskgrTgo6f5+DOCeYk4D3PgVCg4+f5HwAAAP//AwARrjzC4HLqxQAAAABJRU5ErkJggg==",
      "original_width": 32
    },
    "120": {
      "original_height": 120,
      "image": "iVBORw0KGgoAAAANSUhEUgAAAHgAAAB4CAYAAAA5ZDbSAAADyklEQVR4AeydA4x8VxSHz8Mfi6iMamMZlGHNmbh2G9W2GZRRFS7izGu4CKuothEto/XuQ+e82v93Z3HvzfetjW/O7/LdCZYvO7MQb4FQAMGAYEAwIBgQDAgGBCMYEAwIBgQDgmGXQDCCAcGAYEAwIBgQDAiGWDwn2GNvkbYOCfY98Je395J1ZXFBsrEEwZsis70psu84Cfc9QMLDu0WacvV9G0kxM4ngjZYanlJvCu0qnzwBwcFhXRLXL0Sqb4K1TY3Ov0ai/mPFMxAcnVKXqH5BGcsegWAVWlbtiSeLZyBY5W6748lymAMuTXQgF8HRlTcj19eIjmsXrktPuVhckOLHb5pP30oxMyXF0oLIzOR/dORqEvYfh+ANHwrVL5BWyD//ULJkqBSrkneV8ISTqeCNJqpd0LLY/POPxEIQrNVrOhxKh1+SbDQR+J3Ql+pNX30GudYLbu8wqt40GZTsjXEBywWHh3VJVbSHnDWGxAEQbDI8WRt+WRwBwVUnNXSxvaC37FAFVxScv/u2GIBgF+QqDo11Eawb46pSzE6LKyDYZBF/cV5cAcEdneIsCAYELxjEbbs7VY/gxQWpSrD7nuIICC5mp4xWnlwBwTOTGzq1iWALyH/8turkiEt7pBFcfP5h1bGzU1tsqODPP/I6phH8xUeVNsgp4eFdrlQxgmVxwWiFaNsF17jQo0awkr85bjSPHV95k7gAgj//yKwtPrzLBckIVrJkUAzQDXsuSEawVnA22jCWvO26+xgf2yxYSZMhvZbIcPPesbLtoRfoeNksWHvUay88Ug6bTFC525uSo1PqCLYVvXAsG36ppV0i8QVXa7uswhFsI3rFwt87XQbt8h1P2DghgmAlbQy1LFkreNtVNxlUM4Itlkw1l4KdklypTaaaQ3GMdDSR1Qeu0yHUulRzdMq5CLaxd7321J3lBoHWDxJ9DcE2onLWHriupXY5awzp90GwzaSlpCmz4deb45zRYTtx7UI95Lt6NCdD9KINcOC4JWeiGcF6zCHRbE1EE81UMNGMYF3IJ5o9FhwRzf4K1jviiE6tEc0+Ci6j+aqbiWYDwUQzgt2MZj2gVCUj2MdoHmtwjpYK9jSaXTigFMHhiSebR3O53RZim2erdDqSaPa0gqPaBUSzr4LLaG4+Ec2tExPNVDDRjGCimYgmml2tYKIZwUQzEZ02BqUSM1MbEs35e29XW6Cw/AYWLF92ZiFARFsKIBjBgGBAMCAYEAwIBgQDghEMCAYEA4IBwYBgQDCCAcGAYEAwIBgQDAiGnwAAAP//AwABwpQuSeGZvAAAAABJRU5ErkJggg==",
      "original_width": 120
    }
  }
]
