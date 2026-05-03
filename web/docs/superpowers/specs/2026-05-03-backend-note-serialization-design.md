# Backend Note Serialization Design

**Date:** 2026-05-03
**Status:** Approved

## Problem

The frontend (`web/src/api/notes.ts`) contains a data adapter (`mapBackendNote`, `mapAsset`, `snapshotViewsForAsset`, `kindToType`, `mediaTypeToObjectType`) that transforms backend API responses into frontend view models. This creates:

- Business logic duplicated between layers (what `content` to show for link vs. text vs. image)
- Frontend-specific type names (`"composite"`) diverging from backend names (`"complex"`)
- Bugs when the mapping is incomplete or inconsistent (e.g. `kind: "html"` vs `"webpage_html"`)
- Any new field or type requires changes in two places

## Goal

Move all computation to the backend. The frontend receives ready-to-render data and performs only mechanical camelCase conversion. All priorities, type names, and field logic live on the server.

## Naming Convention

Backend naming is authoritative. Frontend types align with backend field names (converted to camelCase).

---

## Backend Changes

### New schemas (`app/modules/content/schemas.py`)

```python
class SnapshotViewResponse(BaseModel):
    kind: str   # "thumbnail" | "markdown" | "pdf" | "webpage_html"
    label: str
    url: str

class NoteObjectResponse(BaseModel):
    id: str
    object_type: str        # "text"|"image"|"link"|"audio"|"video"|"document"
    content: str            # pre-computed: text_content for link/text, url otherwise
    thumbnail_url: str | None = None
    thumbnail_text: str | None = None
    image_width: int | None = None
    image_height: int | None = None
    snapshot_views: list[SnapshotViewResponse] = Field(default_factory=list)
    filename: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    slug: str | None = None     # collection items only
    cover: str | None = None    # collection items only
    created_at: datetime
```

### Updated `NoteCardResponse`

| Field | Change |
|-------|--------|
| `objects: list[NoteObjectResponse]` | **Added** — replaces `assets` and `items` |
| `folder_id: str \| None` | **Added** — `= taxonomy_category.id` |
| `assets` | **Removed** |
| `items` | **Removed** |

All other fields (`id`, `slug`, `kind`, `media_type`, `title`, `tags`, `taxonomy_category`, `is_favorite`, `sort_order`, `created_at`, `updated_at`, `download_url`, `collection`) remain unchanged.

### New function `build_note_objects(note: ContentObject) -> list[NoteObjectResponse]`

Located in `app/modules/content/schemas.py` (or a dedicated `serializers.py`).

**For `kind = "simple"` or `"complex"`** — iterates `note.assets`:
- `object_type` = asset `media_type` (all valid ContentMediaType values map directly; anything else → `"document"`)
- `content` = `asset.text_content` if `object_type in ("link", "text")`, else `asset.url`
- `snapshot_views` = built from flat URL fields:
  - `thumbnail_url` → `{kind: "thumbnail", label: "Миниатюра", url: ...}`
  - `markdown_url` → `{kind: "markdown", label: "Markdown", url: ...}`
  - `pdf_url` → `{kind: "pdf", label: "PDF", url: ...}`
  - `html_url` → `{kind: "webpage_html", label: "HTML", url: ...}`

**For `kind = "collection"`** — iterates `note.items` (child notes):
- `id` = item.id
- `object_type` = first asset's `media_type` (or item's `media_type` if no assets)
- `content` = `first_asset.text_content` if `object_type == "link"`, else `first_asset.url`
- `thumbnail_url` = first asset's `thumbnail_url`
- `slug` = item.slug
- `cover` = first asset's `url` (for non-document, non-link types)
- `snapshot_views` = built from first asset's flat URL fields (same logic as above)

### `folder_id` computation

`folder_id = note.taxonomy_category.id if note.taxonomy_category else None`

Added directly in `NoteCardResponse` serialization (router or service layer).

---

## Frontend Changes

### `src/types/index.ts`

```typescript
// Before                          // After
type NoteType = 'simple'           type NoteKind = 'simple'
              | 'composite'                       | 'complex'
              | 'collection'                      | 'collection'

interface Note {                   interface Note {
  type: NoteType                     kind: NoteKind
  // folderId derived               folderId: string | null  // direct
  objects: NoteObject[]              objects: NoteObject[]
}                                  }

interface NoteObject {             interface NoteObject {
  type: NoteObjectType               objectType: NoteObjectType
  snapshotViews?: SnapshotView[]     snapshotViews: SnapshotView[]  // always present
}                                  }
```

`NoteObjectType` and `SnapshotViewKind` definitions remain unchanged.

### `src/api/notes.ts`

Remove:
- `BackendNote` interface
- `BackendAsset` interface
- `kindToType()`
- `mediaTypeToObjectType()`
- `snapshotViewsForAsset()`
- `mapAsset()`
- `mapBackendNote()`

Replace with a single trivial camelCase converter or direct cast. All API functions (`fetchNotes`, `fetchNote`, `createNote`, etc.) drop the `mapBackendNote()` call.

### Component updates (mechanical find-and-replace)

| Old | New |
|-----|-----|
| `note.type === 'composite'` | `note.kind === 'complex'` |
| `note.type === 'collection'` | `note.kind === 'collection'` |
| `note.type === 'simple'` | `note.kind === 'simple'` |
| `obj.type === 'link'` | `obj.objectType === 'link'` |
| `obj.type === 'image'` | `obj.objectType === 'image'` |
| `obj.type === 'document'` | `obj.objectType === 'document'` |
| `obj.type === 'text'` | `obj.objectType === 'text'` |
| `obj.type === 'audio'` | `obj.objectType === 'audio'` |
| `obj.type === 'video'` | `obj.objectType === 'video'` |

Affected files: `NoteCard.tsx`, `NotePage.tsx`, `useThumbnailPoller.ts`, and any other component referencing `note.type` or `obj.type`.

---

## Scope

**In scope:**
- `NoteCardResponse` and its serialization
- `FileUploadResponse.object` (uses `NoteCardResponse`) — gets `objects[]` automatically
- All endpoints returning `NoteCardResponse` or `NoteListResponse`

**Out of scope:**
- Write endpoints (`CreateNoteRequest`, `UpdateNoteRequest`) — request bodies unchanged
- Enrichment API (`/snapshots`, `/tags`, etc.) — separate schemas, no change
- Auth, folders, taxonomy endpoints

---

## Migration

No DB migration needed — `objects[]` is computed from existing `assets` and `items` at serialization time. The change is purely in the API response shape.
