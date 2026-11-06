import { apiFetch } from '../lib/apiClient.ts'
import { ensureOk, readJson } from '../lib/apiError.ts'
import { makeMarkdownTitle } from '../utils/markdownTitle.ts'
import type {
  Note,
  NotesChangesResult,
  NotesPageResult,
  NotesParams,
  RecommendedNote,
} from '../types/index.ts'

const BASE = '/api/v1/notes'
const JSON_HEADERS = { 'Content-Type': 'application/json' }
export const NOTES_PAGE_SIZE = 60

export interface ReorderNoteItem {
  slug: string
  position: number
}

type RecommendedNoteResponse = {
  id: string
  slug: string
  kind: RecommendedNote['type'] | 'complex'
  media_type: RecommendedNote['mediaType']
  title: string
  score: number
  matched_text: string
  tags?: RecommendedNote['tags']
  created_at: string
  updated_at: string
}

type UpdateNotePayload = Partial<Note> & {
  text?: string | null
}

type UpdateNoteBackendPayload = {
  title?: string | null
  text?: string | null
  tag_names?: string[]
}

export function mapRecommendedNote(item: RecommendedNoteResponse): RecommendedNote {
  return {
    id: item.id,
    slug: item.slug,
    type: item.kind === 'complex' ? 'composite' : item.kind,
    mediaType: item.media_type,
    title: item.title,
    score: item.score,
    matchedText: item.matched_text,
    tags: item.tags ?? [],
    createdAt: item.created_at,
    updatedAt: item.updated_at,
  }
}

export function notesSearchParams(
  params: NotesParams,
  page: { limit?: number; offset?: number } = {},
): URLSearchParams {
  const query = new URLSearchParams({ view: 'card' })
  if (page.limit !== undefined) query.set('limit', String(page.limit))
  if (page.offset) query.set('offset', String(page.offset))
  if (params.search) query.set('search', params.search)
  if (params.search && params.searchMode) query.set('search_mode', params.searchMode)
  if (params.sort) query.set('sort', params.sort)
  params.tags?.forEach(tag => query.append('tags', tag))
  params.folders?.forEach(folder => query.append('folders', folder))
  params.contentTypes?.forEach(type => query.append('types', type))
  params.sources?.forEach(source => query.append('sources', source))
  if (params.favorite !== undefined && params.favorite !== null) query.set('favorite', String(params.favorite))
  if (params.createdAfter) query.set('created_after', params.createdAfter)
  if (params.createdBefore) query.set('created_before', params.createdBefore)
  return query
}

export async function fetchNotesPage(
  params: NotesParams = {},
  signal?: AbortSignal,
  page: { limit?: number; offset?: number } = {},
): Promise<NotesPageResult> {
  const res = await apiFetch(`${BASE}?${notesSearchParams(params, page)}`, { signal })
  const data = await readJson<{ items?: Note[]; nextOffset?: number | null }>(res, 'Не удалось загрузить заметки')
  return { items: data.items ?? [], nextOffset: data.nextOffset ?? null }
}

/** Change feed: cards changed since `cursor` (see `hooks/useNotesChangeFeed`). */
export async function fetchNoteChanges(cursor: string | null, signal?: AbortSignal): Promise<NotesChangesResult> {
  const query = cursor ? `?${new URLSearchParams({ since: cursor })}` : ''
  const res = await apiFetch(`${BASE}/changes${query}`, { signal })
  const data = await readJson<{
    cursor: string
    notes?: Note[]
    removed_ids?: string[]
    reset?: boolean
    has_more?: boolean
  }>(res, 'Не удалось получить обновления заметок')
  return {
    cursor: data.cursor,
    notes: data.notes ?? [],
    removedIds: data.removed_ids ?? [],
    reset: Boolean(data.reset),
    hasMore: Boolean(data.has_more),
  }
}

export async function fetchNoteRecommendations(
  noteRef: string,
  limit = 5,
  signal?: AbortSignal,
): Promise<RecommendedNote[]> {
  const cappedLimit = Math.min(Math.max(limit, 1), 5)
  const res = await apiFetch(
    `${BASE}/${encodeURIComponent(noteRef)}/recommendations?limit=${cappedLimit}`,
    { signal },
  )
  const data = await readJson<{ items?: RecommendedNoteResponse[] }>(res, 'Не удалось загрузить рекомендации')
  return (data.items ?? []).map(mapRecommendedNote)
}

export async function reorderNotes(items: ReorderNoteItem[]): Promise<void> {
  const res = await apiFetch(`${BASE}/order`, {
    method: 'PATCH',
    headers: JSON_HEADERS,
    body: JSON.stringify({ items }),
  })
  await ensureOk(res, 'Failed to reorder notes')
}

export async function fetchTrashNotes(): Promise<Note[]> {
  const data = await readJson<{ items?: Note[] }>(await apiFetch(`${BASE}/trash`), 'Не удалось загрузить корзину')
  return data.items ?? []
}

export async function fetchNote(noteRef: string, signal?: AbortSignal): Promise<Note> {
  return readJson(await apiFetch(`${BASE}/${encodeURIComponent(noteRef)}`, { signal }), 'Не удалось загрузить заметку')
}

export async function decideDeferredLinkSnapshots(
  noteRef: string,
  decision: 'accept' | 'reject',
): Promise<Note> {
  const res = await apiFetch(`${BASE}/${encodeURIComponent(noteRef)}/link-snapshots/decision`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ decision }),
  })
  return readJson(res, 'Не удалось сохранить решение по снапшотам ссылок')
}

export async function createNote(data: Partial<Note>): Promise<Note> {
  const textObj = data.objects?.find(o => o.type === 'text')
  const res = await apiFetch(BASE, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({
      title: data.title ?? null,
      text: textObj?.content ?? null,
      media_type: textObj ? 'text' : null,
      tag_names: data.tags?.map(t => t.name) ?? [],
      file_upload_ids: [],
    }),
  })
  return readJson(res, 'Не удалось создать заметку')
}

async function postFiles(form: FormData): Promise<{ files?: Array<{ id: string }>; object?: Note | null }> {
  const res = await apiFetch(`${BASE}/file/upload`, { method: 'POST', body: form })
  return readJson(res, 'Не удалось загрузить файлы')
}

export async function addFilesToNote(noteId: string, files: File[]): Promise<Note> {
  const form = new FormData()
  form.append('object_id', noteId)
  files.forEach(f => form.append('files', f))
  const body = await postFiles(form)
  if (!body.object) throw new Error('Upload response did not include the updated note')
  return body.object
}

/**
 * Creates a note from uploaded files (and optional markdown text) and returns the created
 * note exactly as the server stored it — there is no separate upload job to poll.
 */
export async function uploadNoteFiles(files: File[], text?: string): Promise<Note> {
  if (files.length === 0) throw new Error('No files to upload')
  const form = new FormData()
  files.forEach(f => form.append('files', f))

  if (!text) {
    form.append('create_object', 'true')
    const body = await postFiles(form)
    if (!body.object) throw new Error('Upload response did not include the created note')
    return body.object
  }

  const uploaded = await postFiles(form)
  const res = await apiFetch(BASE, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({
      title: makeMarkdownTitle(text) || files[0]?.name || '',
      text,
      media_type: 'text',
      tag_names: [],
      file_upload_ids: (uploaded.files ?? []).map(f => f.id),
    }),
  })
  return readJson(res, 'Не удалось создать заметку')
}

export async function removeCollectionItems(collectionSlug: string, itemSlugs: string[]): Promise<void> {
  const res = await apiFetch(`${BASE}/${encodeURIComponent(collectionSlug)}/items`, {
    method: 'DELETE',
    headers: JSON_HEADERS,
    body: JSON.stringify({ item_slugs: itemSlugs }),
  })
  await ensureOk(res, 'Не удалось убрать элементы из коллекции')
}

export async function deleteNotes(slugs: string[]): Promise<void> {
  const res = await apiFetch(BASE, {
    method: 'DELETE',
    headers: JSON_HEADERS,
    body: JSON.stringify({ slugs }),
  })
  await ensureOk(res, 'Не удалось удалить заметки')
}

export async function restoreNote(slug: string): Promise<Note> {
  const res = await apiFetch(`${BASE}/${encodeURIComponent(slug)}/restore`, { method: 'POST' })
  return readJson(res, 'Не удалось восстановить заметку')
}

export async function cleanupTrash(): Promise<{ deletedCount: number }> {
  const res = await apiFetch(`${BASE}/trash/cleanup`, { method: 'POST' })
  const data = await readJson<{ deleted_count?: number }>(res, 'Не удалось очистить корзину')
  return { deletedCount: data.deleted_count ?? 0 }
}

export async function updateNote(noteRef: string, data: UpdateNotePayload): Promise<Note> {
  const textObj = data.objects?.find(o => o.type === 'text')
  const backendPayload: UpdateNoteBackendPayload = {}
  if (data.title !== undefined) backendPayload.title = data.title
  if (data.text !== undefined) backendPayload.text = data.text ?? ''
  else if (textObj) backendPayload.text = textObj.content
  if (data.tags !== undefined) backendPayload.tag_names = data.tags.map(tag => tag.name)

  const res = await apiFetch(`${BASE}/${encodeURIComponent(noteRef)}`, {
    method: 'PATCH',
    headers: JSON_HEADERS,
    body: JSON.stringify(backendPayload),
  })
  return readJson(res, 'Не удалось сохранить заметку')
}
