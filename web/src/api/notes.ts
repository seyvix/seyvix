import { apiFetch } from '../lib/apiClient.ts'
import { makeMarkdownTitle } from '../utils/markdownPaste.ts'
import type { Note, NotesPageResult, NotesParams, RecommendedNote, UploadJob } from '../types'

const BASE = '/api/v1/notes'
export const NOTES_PAGE_SIZE = 60
export const MERGE_NOTES_ENABLED = false
export interface ReorderNoteItem {
  slug: string
  position: number
}

type RecommendedNoteBackendKind = RecommendedNote['type'] | 'complex'

type RecommendedNoteResponse = {
  id: string
  slug: string
  kind: RecommendedNoteBackendKind
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

export async function fetchNotes(
  params: NotesParams = {},
  signal?: AbortSignal,
): Promise<Note[]> {
  return (await fetchNotesPage(params, signal)).items
}

export async function fetchNotesPage(
  params: NotesParams = {},
  signal?: AbortSignal,
  page: { limit?: number; offset?: number } = {},
): Promise<NotesPageResult> {
  const origin = typeof window === 'undefined' ? 'http://localhost' : window.location.origin
  const url = new URL(BASE, origin)
  url.searchParams.set('view', 'card')
  if (page.limit !== undefined) url.searchParams.set('limit', String(page.limit))
  if (page.offset !== undefined && page.offset > 0) {
    url.searchParams.set('offset', String(page.offset))
  }
  if (params.search) url.searchParams.set('search', params.search)
  if (params.search && params.searchMode) url.searchParams.set('search_mode', params.searchMode)
  if (params.sort) url.searchParams.set('sort', params.sort)
  params.tags?.forEach(t => url.searchParams.append('tags', t))
  params.folders?.forEach(f => url.searchParams.append('folders', f))
  params.contentTypes?.forEach(type => url.searchParams.append('types', type))
  params.sources?.forEach(source => url.searchParams.append('sources', source))
  if (params.favorite !== undefined && params.favorite !== null) {
    url.searchParams.set('favorite', String(params.favorite))
  }
  if (params.createdAfter) url.searchParams.set('created_after', params.createdAfter)
  if (params.createdBefore) url.searchParams.set('created_before', params.createdBefore)

  const res = await apiFetch(url.toString(), { signal })
  if (!res.ok) throw new Error('Failed to fetch notes')
  const data: unknown = await res.json()
  if (Array.isArray(data)) return { items: data as Note[], nextOffset: null }
  const payload = data as { items?: Note[]; nextOffset?: number | null }
  return {
    items: payload.items ?? [],
    nextOffset: payload.nextOffset ?? null,
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
  if (!res.ok) throw new Error('Failed to fetch recommendations')
  const data = (await res.json()) as { items?: RecommendedNoteResponse[] }
  return (data.items ?? []).map(mapRecommendedNote)
}

export async function reorderNotes(items: ReorderNoteItem[]): Promise<void> {
  const res = await apiFetch(`${BASE}/order`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items }),
  })
  if (!res.ok) throw new Error('Failed to reorder notes')
}

export async function fetchTrashNotes(): Promise<Note[]> {
  const res = await apiFetch(`${BASE}/trash`)
  if (!res.ok) throw new Error('Failed to fetch trash')
  const data: unknown = await res.json()
  if (Array.isArray(data)) return data as Note[]
  return ((data as { items?: Note[] }).items ?? []) as Note[]
}

export async function fetchNote(noteRef: string): Promise<Note> {
  const res = await apiFetch(`${BASE}/${encodeURIComponent(noteRef)}`)
  if (!res.ok) throw new Error('Failed to fetch note')
  return (await res.json()) as Note
}

export async function decideDeferredLinkSnapshots(
  noteRef: string,
  decision: 'accept' | 'reject',
): Promise<Note> {
  const res = await apiFetch(`${BASE}/${encodeURIComponent(noteRef)}/link-snapshots/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision }),
  })
  if (!res.ok) throw new Error('Failed to update link snapshot decision')
  return (await res.json()) as Note
}

export async function createNote(data: Partial<Note>): Promise<Note> {
  const textObj = data.objects?.find(o => o.type === 'text')
  const backendPayload = {
    title: data.title ?? null,
    text: textObj?.content ?? null,
    media_type: textObj ? 'text' : null,
    tag_names: data.tags?.map(t => t.name) ?? [],
    file_upload_ids: [] as string[],
  }
  const res = await apiFetch(BASE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(backendPayload),
  })
  if (!res.ok) throw new Error('Failed to create note')
  return (await res.json()) as Note
}

export async function addFilesToNote(noteId: string, files: File[]): Promise<Note> {
  const formData = new FormData()
  formData.append('object_id', noteId)
  files.forEach(f => formData.append('files', f))
  const res = await apiFetch(`${BASE}/file/upload`, { method: 'POST', body: formData })
  if (!res.ok) throw new Error('Failed to add files to note')
  const body = await res.json() as Note & { object?: Note }
  return (body.object ?? body) as Note
}

export async function startUploadJob(
  files: File[],
  text?: string,
): Promise<{ jobId: string; noteId: string; noteSlug: string }> {
  if (files.length === 0) throw new Error('No files to upload')

  if (text) {
    const formData = new FormData()
    files.forEach(f => formData.append('files', f))
    const uploadRes = await apiFetch(`${BASE}/file/upload`, { method: 'POST', body: formData })
    if (!uploadRes.ok) throw new Error('Failed to upload files')
    const uploadResult = await uploadRes.json()
    const fileIds: string[] = (uploadResult.files ?? []).map((f: { id: string }) => f.id)

    const title = makeMarkdownTitle(text) || files[0]?.name || ''
    const createRes = await apiFetch(BASE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, text, media_type: 'text', tag_names: [], file_upload_ids: fileIds }),
    })
    if (!createRes.ok) throw new Error('Failed to create note')
    const note = (await createRes.json()) as Note
    return { jobId: note.id, noteId: note.id, noteSlug: note.slug }
  }

  const formData = new FormData()
  files.forEach(f => formData.append('files', f))
  formData.append('create_object', 'true')

  const res = await apiFetch(`${BASE}/file/upload`, { method: 'POST', body: formData })
  if (!res.ok) throw new Error('Failed to upload file')
  const body = await res.json() as Note & { object?: Note }
  const note = (body.object ?? body) as Note
  return {
    jobId: note.id,
    noteId: note.id,
    noteSlug: note.slug,
  }
}

export async function fetchUploadJob(jobId: string): Promise<UploadJob> {
  return { id: jobId, status: 'done', files: [], noteId: jobId }
}

export async function mergeNotes(sourceSlug: string, targetSlug: string, title?: string): Promise<Note> {
  if (!MERGE_NOTES_ENABLED) {
    throw new Error('Merging notes is temporarily disabled')
  }
  const res = await apiFetch(`${BASE}/merge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source_slugs: [sourceSlug], target_slug: targetSlug, title: title ?? null }),
  })
  if (!res.ok) throw new Error('Failed to merge notes')
  return (await res.json()) as Note
}

export async function removeCollectionItems(collectionSlug: string, itemSlugs: string[]): Promise<void> {
  const res = await apiFetch(`${BASE}/${collectionSlug}/items`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ item_slugs: itemSlugs }),
  })
  if (!res.ok) throw new Error('Failed to remove collection items')
}

export async function deleteNotes(slugs: string[]): Promise<void> {
  const res = await apiFetch(BASE, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slugs }),
  })
  if (!res.ok) throw new Error('Failed to delete notes')
}

export async function restoreNote(slug: string): Promise<Note> {
  const res = await apiFetch(`${BASE}/${encodeURIComponent(slug)}/restore`, { method: 'POST', headers: { 'Content-Type': 'application/json' } })
  if (!res.ok) throw new Error('Failed to restore note')
  return (await res.json()) as Note
}

export async function cleanupTrash(): Promise<{ deletedCount: number }> {
  const res = await apiFetch(`${BASE}/trash/cleanup`, { method: 'POST', headers: { 'Content-Type': 'application/json' } })
  if (!res.ok) throw new Error('Failed to cleanup trash')
  const data = await res.json()
  return { deletedCount: data.deleted_count ?? 0 }
}

export async function updateNote(noteRef: string, data: UpdateNotePayload): Promise<Note> {
  const textObj = data.objects?.find(o => o.type === 'text')
  const backendPayload: UpdateNoteBackendPayload = {}
  if (data.title !== undefined) backendPayload.title = data.title
  if ((data as UpdateNotePayload).text !== undefined) {
    backendPayload.text = (data as UpdateNotePayload).text ?? ''
  } else if (textObj) {
    backendPayload.text = textObj.content
  }
  if (data.tags !== undefined) {
    backendPayload.tag_names = data.tags.map(tag => tag.name)
  }

  const res = await apiFetch(`${BASE}/${encodeURIComponent(noteRef)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(backendPayload),
  })
  if (!res.ok) throw new Error('Failed to update note')
  return (await res.json()) as Note
}
