import { apiFetch } from '../lib/apiClient.ts'
import type { Note, NoteObject, NoteObjectType, NoteType, NotesParams, SnapshotView, TaxonomyCategory, UploadJob } from '../types'

const BASE = '/api/v1/notes'
export const MERGE_NOTES_ENABLED = false

// ── Backend schema (subset we care about) ─────────────────────────────────────

interface BackendTag   { id: string; name: string; slug: string }
interface BackendAsset {
  id: string
  role: string
  media_type: string
  filename: string
  mime_type: string | null
  size_bytes: number
  url: string | null
  text_content: string | null
  thumbnail_url: string | null
  thumbnail_text?: string | null
  markdown_url?: string | null
  pdf_url?: string | null
  html_url?: string | null
}

interface BackendNote {
  id: string
  slug: string
  kind: 'simple' | 'complex' | 'collection'
  media_type: string | null
  title: string
  source_filename: string | null
  taxonomy_category: TaxonomyCategory | null
  tags: BackendTag[]
  is_favorite: boolean
  sort_order: number
  created_at: string
  updated_at: string
  download_url: string
  collection: { id: string; slug: string; title: string } | null
  assets: BackendAsset[]
  items: BackendNote[]
}

// ── Mapping ───────────────────────────────────────────────────────────────────

function kindToType(kind: string): NoteType {
  if (kind === 'complex')    return 'composite'
  if (kind === 'collection') return 'collection'
  return 'simple'
}

function mediaTypeToObjectType(mediaType: string | null | undefined): NoteObjectType {
  if (mediaType === 'text' || mediaType === 'image' || mediaType === 'link' || mediaType === 'audio' || mediaType === 'video') {
    return mediaType
  }
  return 'document'
}

function snapshotViewsForAsset(asset: BackendAsset): SnapshotView[] {
  const views: SnapshotView[] = []
  if (asset.thumbnail_url) views.push({ kind: 'thumbnail', label: 'Миниатюра', url: asset.thumbnail_url })
  if (asset.markdown_url) views.push({ kind: 'markdown', label: 'Markdown', url: asset.markdown_url })
  if (asset.pdf_url) views.push({ kind: 'pdf', label: 'PDF', url: asset.pdf_url })
  if (asset.html_url) views.push({ kind: 'html', label: 'HTML', url: asset.html_url })
  return views
}

function mapAsset(asset: BackendAsset, downloadUrl: string, createdAt: string): NoteObject {
  const type = mediaTypeToObjectType(asset.media_type)
  const content = type === 'text'
    ? (asset.text_content ?? asset.url ?? downloadUrl)
    : (asset.url ?? downloadUrl)
  return {
    id: asset.id,
    type,
    content,
    thumbnailUrl: asset.thumbnail_url ?? null,
    thumbnailText: asset.thumbnail_text ?? null,
    snapshotViews: snapshotViewsForAsset(asset),
    filename: asset.filename,
    mimeType: asset.mime_type,
    sizeBytes: asset.size_bytes,
    createdAt,
  }
}

export function mapBackendNote(b: BackendNote): Note {
  let objects: NoteObject[] = []

  if (b.kind === 'collection') {
    objects = b.items.map(item => {
      const firstAsset = item.assets?.[0]
      const type = firstAsset
        ? mediaTypeToObjectType(firstAsset.media_type)
        : mediaTypeToObjectType(item.media_type)
      const content = firstAsset?.url ?? item.download_url
      const thumbnailUrl = type === 'document' ? (firstAsset?.thumbnail_url ?? null) : undefined
      const cover = type === 'document' ? undefined : (firstAsset?.url ?? undefined)
      return {
        id: item.id,
        type,
        content,
        cover,
        thumbnailUrl,
        thumbnailText: firstAsset?.thumbnail_text ?? null,
        snapshotViews: firstAsset ? snapshotViewsForAsset(firstAsset) : [],
        slug: item.slug,
        filename: firstAsset?.filename,
        mimeType: firstAsset?.mime_type ?? null,
        sizeBytes: firstAsset?.size_bytes,
        createdAt: item.created_at,
      }
    })
  } else if (b.assets.length > 0) {
    objects = b.assets.map(a => mapAsset(a, b.download_url, b.created_at))
  } else if (b.media_type === 'text' || b.media_type === null) {
    // Text note — no content in list response; synthetic placeholder
    objects = [{
      id: `${b.id}-text`,
      type: 'text',
      content: b.title,
      createdAt: b.created_at,
    }]
  }

  return {
    id: b.id,
    slug: b.slug,
    type: kindToType(b.kind),
    title: b.title,
    cover: b.assets.length > 0 ? b.download_url : null,
    tags: b.tags.map(t => ({ id: t.id, name: t.name, slug: t.slug })),
    taxonomyCategory: b.taxonomy_category,
    folderId: b.taxonomy_category?.id ?? null,
    objects,
    createdAt: b.created_at,
    updatedAt: b.updated_at,
  }
}

// ── API ───────────────────────────────────────────────────────────────────────

export async function fetchNotes(params: NotesParams = {}): Promise<Note[]> {
  const url = new URL(BASE, window.location.origin)
  if (params.search)          url.searchParams.set('search', params.search)
  // FastAPI list[str] expects repeated params: ?tags=a&tags=b
  params.tags?.forEach(t    => url.searchParams.append('tags',    t))
  params.folders?.forEach(f => url.searchParams.append('folders', f))

  const res = await apiFetch(url.toString())
  if (!res.ok) throw new Error('Failed to fetch notes')
  const data = await res.json()
  const items: BackendNote[] = Array.isArray(data) ? data : (data.items ?? [])
  return items.map(mapBackendNote)
}

export async function fetchNote(slug: string): Promise<Note> {
  const res = await apiFetch(`${BASE}/${slug}`)
  if (!res.ok) throw new Error('Failed to fetch note')
  return mapBackendNote(await res.json())
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
  return mapBackendNote(await res.json())
}

export async function addFilesToNote(noteId: string, files: File[]): Promise<Note> {
  const formData = new FormData()
  formData.append('object_id', noteId)
  files.forEach(f => formData.append('files', f))
  const res = await apiFetch(`${BASE}/file/upload`, { method: 'POST', body: formData })
  if (!res.ok) throw new Error('Failed to add files to note')
  const result = await res.json()
  return mapBackendNote(result.object ?? result)
}

export async function startUploadJob(
  files: File[],
  text?: string,
): Promise<{ jobId: string; noteId: string; noteSlug: string }> {
  if (files.length === 0) throw new Error('No files to upload')

  if (text) {
    // Two-step: upload files as temp → create note with text + file_ids combined
    const formData = new FormData()
    files.forEach(f => formData.append('files', f))
    const uploadRes = await apiFetch(`${BASE}/file/upload`, { method: 'POST', body: formData })
    if (!uploadRes.ok) throw new Error('Failed to upload files')
    const uploadResult = await uploadRes.json()
    const fileIds: string[] = (uploadResult.files ?? []).map((f: { id: string }) => f.id)

    const title = text.split('\n')[0].slice(0, 60) || files[0]?.name || ''
    const createRes = await apiFetch(BASE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, text, media_type: 'text', tag_names: [], file_upload_ids: fileIds }),
    })
    if (!createRes.ok) throw new Error('Failed to create note')
    const note = mapBackendNote(await createRes.json())
    return { jobId: note.id, noteId: note.id, noteSlug: note.slug }
  }

  // Files only: single request with create_object=true
  const formData = new FormData()
  files.forEach(f => formData.append('files', f))
  formData.append('create_object', 'true')

  const res = await apiFetch(`${BASE}/file/upload`, { method: 'POST', body: formData })
  if (!res.ok) throw new Error('Failed to upload file')
  const result = await res.json()
  const obj: BackendNote = result.object ?? result
  return {
    jobId: obj.id,
    noteId: obj.id,
    noteSlug: obj.slug,
  }
}

export async function fetchUploadJob(jobId: string): Promise<UploadJob> {
  // Backend upload is synchronous — upload is already done by the time we poll
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
  return mapBackendNote(await res.json())
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

export async function updateNote(slug: string, data: Partial<Note>): Promise<Note> {
  const res = await apiFetch(`${BASE}/${slug}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to update note')
  return mapBackendNote(await res.json())
}
