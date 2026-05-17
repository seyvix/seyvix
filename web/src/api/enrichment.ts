import { apiFetch } from '../lib/apiClient.ts'
import type { TaxonomyCategory } from '../types'

const API = '/api/v1'

export interface SnapshotArtifact {
  id: string
  content_object_id: string
  source_asset_id: string | null
  artifact_type: string
  filename: string
  mime_type: string
  size_bytes: number
  status: string
  url: string
}

export interface SnapshotJob {
  id: string
  content_object_id: string
  source_asset_id: string | null
  job_type: string
  status: string
  attempts: number
  error_message: string | null
}

export interface TagDetail {
  id: string
  name: string
  slug: string
  description?: string | null
  tag_kind?: string | null
  created_by_type?: string
  source?: string
  confidence?: number | null
  is_archived?: boolean
}

export interface ContentTagAssignment {
  id: string
  content_object_id: string
  tag: TagDetail
  status: 'accepted' | 'suggested' | 'rejected' | string
  assigned_by_type: string
  source: string
  confidence: number | null
  reasoning: string | null
}

export interface ContentTagJob {
  id: string
  content_object_id: string
  job_type: string
  status: string
  attempts: number
  max_attempts: number
  last_error: string | null
  created_at: string
  updated_at: string
}

export interface TaxonomyAssignment {
  id: string
  content_object_id: string
  category_id: string
  category_path: string
  category_name_snapshot: string
  category_path_snapshot: string
  status: 'proposed' | 'accepted' | 'rejected' | 'overridden' | string
  confidence: number | null
  reasoning: string | null
  assigned_by: string
  alternatives: Array<Record<string, unknown>>
  is_current: boolean
}

export interface TaxonomyClassification {
  content_object_id: string
  mode: string
  dry_run: boolean
  assigned: boolean
  assignment_id: string | null
  selected_category: { id: string; name: string; path: string } | null
  status: string
  confidence: number | null
  reasoning: string | null
  semantic_candidates: Array<{
    category_id: string
    category_name: string
    category_path: string
    score: number
    chunk_id: string
  }>
  classification_text_preview: string
  would_assign: boolean
  would_status: string
  would_category: { id: string; name: string; path: string } | null
}

export interface TaxonomyClassificationJob {
  id: string
  content_object_id: string
  job_type: string
  status: string
  attempts: number
  max_attempts: number
  result_status: string | null
  assignment_id: string | null
  last_error: string | null
  created_at: string
  updated_at: string
}

async function readJson<T>(res: Response, fallbackMessage: string): Promise<T> {
  if (!res.ok) {
    let message = fallbackMessage
    try {
      const body = await res.json()
      message = body?.error?.message ?? body?.message ?? message
    } catch {
      message = res.statusText || message
    }
    throw new Error(message)
  }
  return res.json() as Promise<T>
}

const cyrillicTranslit: Record<string, string> = {
  а: 'a',
  б: 'b',
  в: 'v',
  г: 'g',
  д: 'd',
  е: 'e',
  ё: 'e',
  ж: 'zh',
  з: 'z',
  и: 'i',
  й: 'j',
  к: 'k',
  л: 'l',
  м: 'm',
  н: 'n',
  о: 'o',
  п: 'p',
  р: 'r',
  с: 's',
  т: 't',
  у: 'u',
  ф: 'f',
  х: 'h',
  ц: 'c',
  ч: 'ch',
  ш: 'sh',
  щ: 'sch',
  ъ: '',
  ы: 'y',
  ь: '',
  э: 'e',
  ю: 'yu',
  я: 'ya',
}

function slugify(value: string): string {
  const transliterated = value
    .trim()
    .toLowerCase()
    .split('')
    .map(char => cyrillicTranslit[char] ?? char)
    .join('')
  return transliterated.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'category'
}

export async function fetchSnapshotArtifacts(contentObjectId: string): Promise<SnapshotArtifact[]> {
  const params = new URLSearchParams({ content_object_id: contentObjectId })
  const res = await apiFetch(`${API}/snapshots/artifacts?${params}`)
  const data = await readJson<{ items: SnapshotArtifact[] }>(res, 'Failed to fetch snapshot artifacts')
  return data.items
}

export async function fetchSnapshotJobs(contentObjectId: string): Promise<SnapshotJob[]> {
  const params = new URLSearchParams({ content_object_id: contentObjectId })
  const res = await apiFetch(`${API}/snapshots/jobs?${params}`)
  const data = await readJson<{ items: SnapshotJob[] }>(res, 'Failed to fetch snapshot jobs')
  return data.items
}

export async function reprocessSnapshotMarkdown(
  contentObjectId: string,
  sourceAssetId: string,
): Promise<{ queued_count: number; job_ids: string[]; source_asset_ids: string[] }> {
  const res = await apiFetch(`${API}/snapshots/reprocess`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      content_object_id: contentObjectId,
      source_asset_id: sourceAssetId,
      job_types: ['markdown'],
      force: true,
    }),
  })
  return readJson(res, 'Failed to queue snapshot reprocess')
}

export async function fetchTags(): Promise<TagDetail[]> {
  const res = await apiFetch(`${API}/tags`)
  return readJson<TagDetail[]>(res, 'Failed to fetch tags')
}

export async function createTag(name: string): Promise<TagDetail> {
  const res = await apiFetch(`${API}/tags`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
  return readJson<TagDetail>(res, 'Failed to create tag')
}

export async function createOrFindTag(name: string): Promise<TagDetail> {
  const normalized = slugify(name)
  const existing = (await fetchTags()).find((tag) => tag.slug === normalized || tag.name.toLowerCase() === name.trim().toLowerCase())
  if (existing) return existing
  try {
    return await createTag(name)
  } catch {
    const retry = (await fetchTags()).find((tag) => tag.slug === normalized)
    if (retry) return retry
    throw new Error('Failed to create tag')
  }
}

export async function fetchContentTags(contentObjectId: string): Promise<ContentTagAssignment[]> {
  const res = await apiFetch(`${API}/content/${contentObjectId}/tags`)
  return readJson<ContentTagAssignment[]>(res, 'Failed to fetch content tags')
}

export async function assignExistingTagToContent(contentObjectId: string, tagId: string): Promise<ContentTagAssignment> {
  const res = await apiFetch(`${API}/content/${contentObjectId}/tags`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tag_id: tagId }),
  })
  return readJson<ContentTagAssignment>(res, 'Failed to assign tag')
}

export async function removeTagFromContent(contentObjectId: string, tagId: string): Promise<void> {
  const res = await apiFetch(`${API}/content/${contentObjectId}/tags/${tagId}`, { method: 'DELETE', headers: { 'Content-Type': 'application/json' } })
  if (!res.ok) throw new Error('Failed to remove tag')
}

export async function requestContentTagSuggestions(contentObjectId: string): Promise<{ job_id: string; status: string }> {
  const res = await apiFetch(`${API}/content/${contentObjectId}/tags/suggest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dry_run: false }),
  })
  return readJson<{ job_id: string; status: string }>(res, 'Failed to request tag suggestions')
}

export async function fetchContentTagSuggestions(contentObjectId: string): Promise<ContentTagAssignment[]> {
  const res = await apiFetch(`${API}/content/${contentObjectId}/tags/suggestions`)
  return readJson<ContentTagAssignment[]>(res, 'Failed to fetch tag suggestions')
}

export async function fetchContentTagJobs(contentObjectId: string): Promise<ContentTagJob[]> {
  const res = await apiFetch(`${API}/content/${contentObjectId}/tags/jobs`)
  const data = await readJson<{ items: ContentTagJob[] }>(res, 'Failed to fetch tag jobs')
  return data.items
}

export async function acceptTagSuggestion(contentObjectId: string, assignmentId: string): Promise<ContentTagAssignment> {
  const res = await apiFetch(`${API}/content/${contentObjectId}/tags/suggestions/${assignmentId}/accept`, { method: 'POST', headers: { 'Content-Type': 'application/json' } })
  return readJson<ContentTagAssignment>(res, 'Failed to accept tag suggestion')
}

export async function rejectTagSuggestion(contentObjectId: string, assignmentId: string): Promise<ContentTagAssignment> {
  const res = await apiFetch(`${API}/content/${contentObjectId}/tags/suggestions/${assignmentId}/reject`, { method: 'POST', headers: { 'Content-Type': 'application/json' } })
  return readJson<ContentTagAssignment>(res, 'Failed to reject tag suggestion')
}

export async function searchTaxonomyCategories(query: string): Promise<TaxonomyCategory[]> {
  const params = new URLSearchParams({ q: query })
  const res = await apiFetch(`${API}/taxonomy/categories/search?${params}`)
  return readJson<TaxonomyCategory[]>(res, 'Failed to search categories')
}

export async function createTaxonomyCategory(name: string, parentId?: string | null): Promise<TaxonomyCategory> {
  const trimmed = name.trim()
  const res = await apiFetch(`${API}/taxonomy/categories`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: trimmed,
      slug: slugify(trimmed),
      parent_id: parentId ?? null,
    }),
  })
  return readJson<TaxonomyCategory>(res, 'Failed to create category')
}

export async function fetchTaxonomyAssignments(contentObjectId: string): Promise<TaxonomyAssignment[]> {
  const res = await apiFetch(`${API}/taxonomy/content/${contentObjectId}/assignments`)
  return readJson<TaxonomyAssignment[]>(res, 'Failed to fetch taxonomy assignments')
}

export async function assignCategoryToContent(contentObjectId: string, categoryId: string): Promise<TaxonomyAssignment> {
  const res = await apiFetch(`${API}/taxonomy/content/${contentObjectId}/assignments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ category_id: categoryId }),
  })
  return readJson<TaxonomyAssignment>(res, 'Failed to assign category')
}

export async function triggerTaxonomyClassification(contentObjectId: string): Promise<TaxonomyClassification> {
  const res = await apiFetch(`${API}/taxonomy/content/${contentObjectId}/classify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: 'semantic_only', dry_run: false }),
  })
  return readJson<TaxonomyClassification>(res, 'Failed to classify content')
}

export async function fetchTaxonomyClassificationJobs(contentObjectId: string): Promise<TaxonomyClassificationJob[]> {
  const res = await apiFetch(`${API}/taxonomy/content/${contentObjectId}/classification-jobs`)
  const data = await readJson<{ items: TaxonomyClassificationJob[] }>(res, 'Failed to fetch taxonomy jobs')
  return data.items
}

export async function acceptTaxonomyAssignment(contentObjectId: string, assignmentId: string): Promise<TaxonomyAssignment> {
  const res = await apiFetch(`${API}/taxonomy/content/${contentObjectId}/assignments/${assignmentId}/accept`, { method: 'POST', headers: { 'Content-Type': 'application/json' } })
  return readJson<TaxonomyAssignment>(res, 'Failed to accept category')
}

export async function rejectTaxonomyAssignment(contentObjectId: string, assignmentId: string): Promise<TaxonomyAssignment> {
  const res = await apiFetch(`${API}/taxonomy/content/${contentObjectId}/assignments/${assignmentId}/reject`, { method: 'POST', headers: { 'Content-Type': 'application/json' } })
  return readJson<TaxonomyAssignment>(res, 'Failed to reject category')
}
