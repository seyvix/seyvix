# Note Detail Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a full-page note detail view (`/notes/:noteSlug`) with a vertical content stream and inline edit mode.

**Architecture:** Single `NotePage.tsx` reads note from TanStack Query (`useQuery(['note', slug])`), renders a scrollable page with hero + metadata + object stream. Edit mode is a local boolean toggle — no separate route. Each object type has its own renderer component defined in the same file.

**Tech Stack:** React 19, TanStack Query v5, framer-motion, CSS Modules, lucide-react, React Router v6.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `src/pages/NotePage.tsx` | Modify (rewrite stub) | Full note detail page + edit mode |
| `src/pages/NotePage.module.css` | Create | All styles for NotePage |
| `src/hooks/useNote.ts` | Create | `useQuery` wrapper for `fetchNote(slug)` |

---

### Task 1: `useNote` hook

**Files:**
- Create: `src/hooks/useNote.ts`

- [ ] **Step 1: Create the hook**

```ts
// src/hooks/useNote.ts
import { useQuery } from '@tanstack/react-query'
import { fetchNote } from '../api/notes'

export function useNote(slug: string) {
  return useQuery({
    queryKey: ['note', slug],
    queryFn: () => fetchNote(slug),
    staleTime: 1000 * 60 * 5,
  })
}
```

- [ ] **Step 2: Verify the file is correct**

Check `src/api/notes.ts` — `fetchNote(slug: string): Promise<Note>` already exists at line 14. The hook is ready.

---

### Task 2: CSS — NotePage styles

**Files:**
- Create: `src/pages/NotePage.module.css`

- [ ] **Step 1: Create the stylesheet**

```css
/* src/pages/NotePage.module.css */

/* ── Page shell ── */
.page {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  background: var(--color-bg);
}

/* ── Top bar ── */
.topBar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-bottom: 1px solid var(--color-border);
  position: sticky;
  top: 0;
  background: var(--color-bg);
  z-index: 10;
  gap: 12px;
}

.backBtn {
  all: unset;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  cursor: pointer;
  padding: 6px 10px;
  border-radius: var(--radius-sm);
  transition: background var(--duration-fast), color var(--duration-fast);
}

.backBtn:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
}

.topBarActions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.editBtn {
  all: unset;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  font-family: var(--font-family);
  color: var(--color-text-secondary);
  cursor: pointer;
  padding: 6px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-border);
  transition: background var(--duration-fast), color var(--duration-fast), border-color var(--duration-fast);
}

.editBtn:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
  border-color: #555;
}

.editBtnActive {
  background: var(--color-accent);
  color: #fff;
  border-color: var(--color-accent);
}

.editBtnActive:hover {
  background: var(--color-accent-hover);
  border-color: var(--color-accent-hover);
  color: #fff;
}

.saveBtn {
  all: unset;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  font-family: var(--font-family);
  color: #fff;
  background: var(--color-accent);
  cursor: pointer;
  padding: 6px 16px;
  border-radius: var(--radius-sm);
  transition: opacity var(--duration-fast);
}

.saveBtn:hover {
  opacity: 0.85;
}

/* ── Content ── */
.content {
  flex: 1;
  max-width: 680px;
  width: 100%;
  margin: 0 auto;
  padding: 0 0 64px;
}

/* ── Hero ── */
.hero {
  width: 100%;
  aspect-ratio: 16 / 7;
  overflow: hidden;
  margin-bottom: 28px;
}

.heroImg {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.heroGradient {
  width: 100%;
  height: 100%;
  background: linear-gradient(160deg, #0d0f1a 0%, #151825 60%, #1a1420 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px;
  box-sizing: border-box;
}

.heroTitle {
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-semibold);
  color: rgba(255, 255, 255, 0.15);
  line-height: 1.4;
  text-align: center;
  font-family: var(--font-family);
}

/* ── Metadata ── */
.meta {
  padding: 0 24px 24px;
}

.title {
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  line-height: 1.3;
  margin-bottom: 12px;
}

.titleInput {
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-semibold);
  font-family: var(--font-family);
  color: var(--color-text-primary);
  background: transparent;
  border: none;
  border-bottom: 1.5px solid var(--color-accent);
  outline: none;
  width: 100%;
  line-height: 1.3;
  margin-bottom: 12px;
  padding: 0 0 4px;
  box-shadow: 0 1px 0 0 rgba(99, 102, 241, 0.35);
}

.metaRow {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.tag {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 20px;
  line-height: 1.4;
}

.date {
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
  letter-spacing: 0.04em;
}

/* ── Object stream ── */
.stream {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 0 24px;
}

/* Image object */
.objImage {
  width: 100%;
  border-radius: var(--radius-md);
  overflow: hidden;
  cursor: zoom-in;
}

.objImage img {
  width: 100%;
  display: block;
  pointer-events: none;
}

/* Text object */
.objText {
  font-size: var(--font-size-base);
  color: var(--color-text-primary);
  line-height: 1.75;
  white-space: pre-wrap;
}

.objTextarea {
  font-size: var(--font-size-base);
  font-family: var(--font-family);
  color: var(--color-text-primary);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  outline: none;
  width: 100%;
  min-height: 120px;
  resize: vertical;
  line-height: 1.75;
  padding: 12px 16px;
  box-sizing: border-box;
}

.objTextarea:focus {
  border-color: var(--color-accent);
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.15);
}

/* Link object */
.objLink {
  display: flex;
  align-items: center;
  gap: 12px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 14px 16px;
  text-decoration: none;
  transition: border-color var(--duration-fast), background var(--duration-fast);
}

.objLink:hover {
  border-color: #3a3a3a;
  background: var(--color-surface-hover);
}

.objLinkIcon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: rgba(99, 102, 241, 0.1);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-accent);
  flex-shrink: 0;
}

.objLinkFavicon {
  width: 20px;
  height: 20px;
  border-radius: 4px;
  display: block;
}

.objLinkText {
  flex: 1;
  min-width: 0;
}

.objLinkDomain {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.objLinkUrl {
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-top: 2px;
}

.objLinkArrow {
  color: var(--color-text-secondary);
  flex-shrink: 0;
}

/* Document object */
.objDoc {
  display: flex;
  align-items: center;
  gap: 12px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 12px 16px;
  text-decoration: none;
  transition: border-color var(--duration-fast);
}

.objDoc:hover {
  border-color: #3a3a3a;
}

.objDocCover {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-sm);
  object-fit: cover;
  flex-shrink: 0;
}

.objDocIconWrap {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-sm);
  background: rgba(180, 110, 40, 0.15);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #c47830;
  flex-shrink: 0;
}

.objDocText {
  flex: 1;
  min-width: 0;
}

.objDocName {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.objDocExt {
  font-size: 9px;
  font-weight: var(--font-weight-semibold);
  background: rgba(180, 110, 40, 0.18);
  color: #c47830;
  padding: 1px 4px;
  border-radius: 3px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-top: 3px;
  display: inline-block;
}

.objDocDownload {
  color: var(--color-text-secondary);
  flex-shrink: 0;
  transition: color var(--duration-fast);
}

.objDocDownload:hover {
  color: var(--color-text-primary);
}

/* Edit mode: delete object button */
.objWrapper {
  position: relative;
}

.objDeleteBtn {
  all: unset;
  position: absolute;
  top: 8px;
  right: 8px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.7);
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background var(--duration-fast), color var(--duration-fast);
  z-index: 1;
}

.objDeleteBtn:hover {
  background: var(--color-danger);
  color: #fff;
}

/* Not found */
.notFound {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-secondary);
  font-size: var(--font-size-base);
}
```

---

### Task 3: NotePage component

**Files:**
- Modify: `src/pages/NotePage.tsx`

- [ ] **Step 1: Rewrite the page**

```tsx
// src/pages/NotePage.tsx
import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, ExternalLink, FileText, Download, X } from 'lucide-react'
import { useNote } from '../hooks/useNote'
import { useUpdateNote } from '../hooks/useUpdateNote'
import { getTagColor } from '../utils/tagColor'
import type { Note, NoteObject, Tag } from '../types'
import styles from './NotePage.module.css'

// ─── Object renderers ──────────────────────────────────────────────────────────

function ImageObj({ obj, isEditing, onDelete }: { obj: NoteObject; isEditing: boolean; onDelete: () => void }) {
  return (
    <div className={`${styles.objWrapper} ${styles.objImage}`}>
      <img src={obj.content} alt="" onClick={() => window.open(obj.content, '_blank')} />
      {isEditing && (
        <button className={styles.objDeleteBtn} onClick={onDelete} title="Удалить">
          <X size={12} />
        </button>
      )}
    </div>
  )
}

function LinkObj({ obj, isEditing, onDelete }: { obj: NoteObject; isEditing: boolean; onDelete: () => void }) {
  let domain = ''
  let favicon: string | null = null
  try {
    const u = new URL(obj.content)
    domain = u.hostname.replace(/^www\./, '')
    favicon = `https://www.google.com/s2/favicons?domain=${u.hostname}&sz=64`
  } catch { /* ignore */ }

  return (
    <div className={styles.objWrapper}>
      <a className={styles.objLink} href={obj.content} target="_blank" rel="noopener noreferrer">
        <div className={styles.objLinkIcon}>
          {favicon
            ? <img src={favicon} alt="" className={styles.objLinkFavicon} />
            : <ExternalLink size={16} />
          }
        </div>
        <div className={styles.objLinkText}>
          <div className={styles.objLinkDomain}>{domain || obj.content}</div>
          <div className={styles.objLinkUrl}>{obj.content}</div>
        </div>
        <ExternalLink size={14} className={styles.objLinkArrow} />
      </a>
      {isEditing && (
        <button className={styles.objDeleteBtn} onClick={onDelete} title="Удалить">
          <X size={12} />
        </button>
      )}
    </div>
  )
}

function DocObj({ obj, isEditing, onDelete }: { obj: NoteObject; isEditing: boolean; onDelete: () => void }) {
  const ext  = obj.content.includes('.') ? obj.content.split('.').pop()!.toUpperCase().slice(0, 4) : 'FILE'
  const name = obj.content.replace(/\.[^.]+$/, '')

  return (
    <div className={styles.objWrapper}>
      <div className={styles.objDoc}>
        {obj.cover
          ? <img src={obj.cover} alt="" className={styles.objDocCover} />
          : <div className={styles.objDocIconWrap}><FileText size={20} /></div>
        }
        <div className={styles.objDocText}>
          <div className={styles.objDocName}>{name}</div>
          <span className={styles.objDocExt}>{ext}</span>
        </div>
        <Download size={16} className={styles.objDocDownload} />
      </div>
      {isEditing && (
        <button className={styles.objDeleteBtn} onClick={onDelete} title="Удалить">
          <X size={12} />
        </button>
      )}
    </div>
  )
}

function TextObj({
  obj,
  isEditing,
  editValue,
  onChangeEdit,
  onDelete,
}: {
  obj: NoteObject
  isEditing: boolean
  editValue: string
  onChangeEdit: (v: string) => void
  onDelete: () => void
}) {
  if (isEditing) {
    return (
      <div className={styles.objWrapper}>
        <textarea
          className={styles.objTextarea}
          value={editValue}
          onChange={e => onChangeEdit(e.target.value)}
        />
        <button className={styles.objDeleteBtn} onClick={onDelete} title="Удалить">
          <X size={12} />
        </button>
      </div>
    )
  }
  return <p className={styles.objText}>{obj.content}</p>
}

// ─── Tags ──────────────────────────────────────────────────────────────────────

function TagList({ tags }: { tags: Tag[] }) {
  if (tags.length === 0) return null
  return (
    <>
      {tags.map(tag => {
        const { bg, text } = getTagColor(tag.name)
        return (
          <span key={tag.id} className={styles.tag} style={{ background: bg, color: text }}>
            {tag.name}
          </span>
        )
      })}
    </>
  )
}

// ─── Hero ──────────────────────────────────────────────────────────────────────

function Hero({ note }: { note: Note }) {
  const imageObj = note.objects.find(o => o.type === 'image')
  return (
    <div className={styles.hero}>
      {imageObj
        ? <img src={imageObj.content} alt="" className={styles.heroImg} />
        : <div className={styles.heroGradient}>
            <span className={styles.heroTitle}>{note.title}</span>
          </div>
      }
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function NotePage() {
  const { noteSlug } = useParams<{ noteSlug: string }>()
  const navigate = useNavigate()
  const { data: note, isLoading } = useNote(noteSlug!)
  const { mutate: updateNote } = useUpdateNote()

  const [isEditing,   setIsEditing]   = useState(false)
  const [editTitle,   setEditTitle]   = useState('')
  // Map of objId → edited text (only for text objects)
  const [editTexts,   setEditTexts]   = useState<Record<string, string>>({})
  // Set of deleted object ids
  const [deletedObjs, setDeletedObjs] = useState<Set<string>>(new Set())

  function enterEdit() {
    if (!note) return
    setEditTitle(note.title)
    const texts: Record<string, string> = {}
    note.objects.filter(o => o.type === 'text').forEach(o => { texts[o.id] = o.content })
    setEditTexts(texts)
    setDeletedObjs(new Set())
    setIsEditing(true)
  }

  function cancelEdit() {
    setIsEditing(false)
  }

  function saveEdit() {
    if (!note) return
    const objects = note.objects
      .filter(o => !deletedObjs.has(o.id))
      .map(o => o.type === 'text' ? { ...o, content: editTexts[o.id] ?? o.content } : o)

    updateNote({ slug: note.slug, data: { title: editTitle || note.title, objects } })
    setIsEditing(false)
  }

  function deleteObj(id: string) {
    setDeletedObjs(prev => new Set([...prev, id]))
  }

  if (isLoading) return null

  if (!note) {
    return (
      <div className={styles.page}>
        <div className={styles.notFound}>Заметка не найдена</div>
      </div>
    )
  }

  const visibleObjects = note.objects.filter(o => !deletedObjs.has(o.id))

  const formattedDate = new Date(note.updatedAt).toLocaleDateString('ru-RU', {
    day: 'numeric', month: 'long', year: 'numeric',
  })

  return (
    <div className={styles.page}>
      {/* Top bar */}
      <div className={styles.topBar}>
        <button className={styles.backBtn} onClick={() => navigate(-1)}>
          <ArrowLeft size={14} />
          Заметки
        </button>
        <div className={styles.topBarActions}>
          {isEditing ? (
            <>
              <button className={styles.editBtn} onClick={cancelEdit}>Отмена</button>
              <button className={styles.saveBtn} onClick={saveEdit}>Сохранить</button>
            </>
          ) : (
            <button className={styles.editBtn} onClick={enterEdit}>Редактировать</button>
          )}
        </div>
      </div>

      {/* Content */}
      <div className={styles.content}>
        <Hero note={note} />

        {/* Metadata */}
        <div className={styles.meta}>
          {isEditing
            ? <input
                autoFocus
                className={styles.titleInput}
                value={editTitle}
                onChange={e => setEditTitle(e.target.value)}
              />
            : <h1 className={styles.title}>{note.title}</h1>
          }
          <div className={styles.metaRow}>
            <TagList tags={note.tags} />
            <span className={styles.date}>{formattedDate}</span>
          </div>
        </div>

        {/* Object stream */}
        <div className={styles.stream}>
          {visibleObjects.map(obj => {
            if (obj.type === 'image') {
              return (
                <ImageObj
                  key={obj.id}
                  obj={obj}
                  isEditing={isEditing}
                  onDelete={() => deleteObj(obj.id)}
                />
              )
            }
            if (obj.type === 'link') {
              return (
                <LinkObj
                  key={obj.id}
                  obj={obj}
                  isEditing={isEditing}
                  onDelete={() => deleteObj(obj.id)}
                />
              )
            }
            if (obj.type === 'document') {
              return (
                <DocObj
                  key={obj.id}
                  obj={obj}
                  isEditing={isEditing}
                  onDelete={() => deleteObj(obj.id)}
                />
              )
            }
            if (obj.type === 'text') {
              return (
                <TextObj
                  key={obj.id}
                  obj={obj}
                  isEditing={isEditing}
                  editValue={editTexts[obj.id] ?? obj.content}
                  onChangeEdit={v => setEditTexts(prev => ({ ...prev, [obj.id]: v }))}
                  onDelete={() => deleteObj(obj.id)}
                />
              )
            }
            return null
          })}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify imports exist**

Check that `src/hooks/useUpdateNote.ts` exports `useUpdateNote` — it was created in a previous session.
Check that `src/utils/tagColor.ts` exports `getTagColor` — used in `NoteCard.tsx`.

---

### Task 4: MSW handler for PATCH `/api/notes/:slug`

The `updateNote` API already calls `PATCH /api/notes/:slug`. Check that MSW handles it.

**Files:**
- Modify: `src/mocks/handlers/notes.ts`

- [ ] **Step 1: Check if PATCH handler exists**

Search in `src/mocks/handlers/notes.ts` for `http.patch`. If it's already there and handles `objects` field — skip this task.

- [ ] **Step 2: Add PATCH handler if missing**

Add after `http.get('/api/notes/:slug', ...)`:

```ts
http.patch('/api/notes/:slug', async ({ params, request }) => {
  const slug = params.slug as string
  const idx  = notes.findIndex(n => n.slug === slug)
  if (idx === -1) return HttpResponse.json({ error: 'Not found' }, { status: 404 })
  const body = await request.json() as Partial<Note>
  notes[idx] = { ...notes[idx], ...body, updatedAt: new Date().toISOString() }
  return HttpResponse.json(notes[idx])
}),
```

---

### Self-Review Checklist

- [x] **Spec coverage:** Hero ✓, title ✓, tags+date ✓, object stream (image/link/doc/text) ✓, edit mode (title input, text textarea, delete obj) ✓, save/cancel ✓
- [x] **No placeholders:** All steps have complete code
- [x] **Type consistency:** `NoteObject`, `Note`, `Tag` — all from `src/types/index.ts`. `useUpdateNote({ slug, data })` matches existing hook signature.
- [x] **PATCH handler:** Added in Task 4 if not present
