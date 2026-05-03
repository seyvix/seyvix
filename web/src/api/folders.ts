import { apiFetch } from '../lib/apiClient.ts'
import type {
  CategoryProfile,
  CategoryProfileDraft,
  Folder,
  FolderDetail,
  FolderNoteSummary,
  Tag,
  TaxonomySettings,
} from '../types'

const BASE = '/api/v1/folders'

// Backend shape from FolderTreeResponse / FolderTreeItem
export interface BackendFolderItem {
  id: string
  name: string
  slug: string
  path: string
  direct_count?: number
  total_count?: number
  children?: BackendFolderItem[]
}

interface BackendFolderNote {
  id: string
  slug: string
  title: string
  taxonomy_category?: {
    id: string
    name: string
    slug: string
    path: string
  } | null
  created_at: string
  updated_at: string
}

interface BackendFolderDetail {
  folder: BackendFolderItem
  tags?: Tag[]
  notes?: BackendFolderNote[]
}

interface BackendTaxonomySettings {
  owner_user_id: string
  category_profile_editing_enabled: boolean
  trash_enabled: boolean
  trash_retention_days: number
}

interface BackendCategoryProfile {
  id?: string
  category_id: string
  summary: string | null
  keywords: string[]
  positive_examples: string[]
  negative_examples: string[]
  created_at?: string
  updated_at?: string
}

interface BackendCategoryProfileDraft {
  summary: string | null
  keywords: string[]
  positive_examples: string[]
  negative_examples: string[]
  reasoning: string
}

function encodeFolderPath(path: string): string {
  return path.split('/').map(encodeURIComponent).join('/')
}

function slugify(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'category'
}

export function mapBackendFolder(item: BackendFolderItem, parentId: string | null = null): Folder {
  return {
    id: item.id,
    slug: item.slug,
    name: item.name,
    path: item.path,
    directCount: item.direct_count ?? 0,
    totalCount: item.total_count ?? 0,
    parentId,
    children: (item.children ?? []).map(c => mapBackendFolder(c, item.id)),
  }
}

function mapBackendTaxonomySettings(item: BackendTaxonomySettings): TaxonomySettings {
  return {
    ownerUserId: item.owner_user_id,
    categoryProfileEditingEnabled: item.category_profile_editing_enabled,
    trashEnabled: item.trash_enabled,
    trashRetentionDays: item.trash_retention_days,
  }
}

function mapBackendCategoryProfile(item: BackendCategoryProfile): CategoryProfile {
  return {
    id: item.id,
    categoryId: item.category_id,
    summary: item.summary,
    keywords: item.keywords ?? [],
    positiveExamples: item.positive_examples ?? [],
    negativeExamples: item.negative_examples ?? [],
    createdAt: item.created_at,
    updatedAt: item.updated_at,
  }
}

function mapBackendCategoryProfileDraft(item: BackendCategoryProfileDraft): CategoryProfileDraft {
  return {
    summary: item.summary,
    keywords: item.keywords ?? [],
    positiveExamples: item.positive_examples ?? [],
    negativeExamples: item.negative_examples ?? [],
    reasoning: item.reasoning,
  }
}

function mapBackendNoteSummary(note: BackendFolderNote): FolderNoteSummary {
  return {
    id: note.id,
    slug: note.slug,
    title: note.title,
    taxonomyCategory: note.taxonomy_category ?? null,
    createdAt: note.created_at,
    updatedAt: note.updated_at,
  }
}

export function mapBackendFolderDetail(data: BackendFolderDetail): FolderDetail {
  return {
    category: mapBackendFolder(data.folder),
    tags: data.tags ?? [],
    notes: (data.notes ?? []).map(mapBackendNoteSummary),
  }
}

export async function fetchFolders(): Promise<Folder[]> {
  const res = await apiFetch(BASE)
  if (!res.ok) throw new Error('Failed to fetch folders')
  const data = await res.json()
  // Backend returns { items: FolderTreeItem[] }
  const items: BackendFolderItem[] = Array.isArray(data) ? data : (data.items ?? [])
  return items.map(item => mapBackendFolder(item))
}

export async function fetchFolder(path: string): Promise<FolderDetail> {
  const res = await apiFetch(`${BASE}/${encodeFolderPath(path)}`)
  if (!res.ok) throw new Error('Failed to fetch folder')
  return mapBackendFolderDetail(await res.json())
}

export async function reclassifyInbox(): Promise<{ enqueuedCount: number }> {
  const res = await apiFetch('/api/v1/taxonomy/content/inbox/reclassify', { method: 'POST', headers: { 'Content-Type': 'application/json' } })
  if (!res.ok) throw new Error('Failed to reclassify inbox')
  const data = await res.json()
  return { enqueuedCount: data.enqueued_count ?? 0 }
}

export async function fetchTaxonomySettings(): Promise<TaxonomySettings> {
  const res = await apiFetch('/api/v1/taxonomy/settings')
  if (!res.ok) throw new Error('Failed to fetch taxonomy settings')
  return mapBackendTaxonomySettings(await res.json())
}

export async function updateTaxonomySettings(payload: {
  categoryProfileEditingEnabled?: boolean
  trashEnabled?: boolean
  trashRetentionDays?: number
}): Promise<TaxonomySettings> {
  const body: Record<string, boolean | number> = {}
  if (payload.categoryProfileEditingEnabled !== undefined) {
    body.category_profile_editing_enabled = payload.categoryProfileEditingEnabled
  }
  if (payload.trashEnabled !== undefined) body.trash_enabled = payload.trashEnabled
  if (payload.trashRetentionDays !== undefined) body.trash_retention_days = payload.trashRetentionDays
  const res = await apiFetch('/api/v1/taxonomy/settings', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error('Failed to update taxonomy settings')
  return mapBackendTaxonomySettings(await res.json())
}

export async function fetchCategoryProfile(categoryId: string): Promise<CategoryProfile> {
  const res = await apiFetch(`/api/v1/taxonomy/categories/${categoryId}/profile`)
  if (res.status === 404) {
    return {
      categoryId,
      summary: null,
      keywords: [],
      positiveExamples: [],
      negativeExamples: [],
    }
  }
  if (!res.ok) throw new Error('Failed to fetch category profile')
  return mapBackendCategoryProfile(await res.json())
}

export async function updateCategoryProfile(
  categoryId: string,
  profile: Pick<CategoryProfile, 'summary' | 'keywords' | 'positiveExamples' | 'negativeExamples'>,
): Promise<CategoryProfile> {
  const res = await apiFetch(`/api/v1/taxonomy/categories/${categoryId}/profile`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      summary: profile.summary,
      keywords: profile.keywords,
      positive_examples: profile.positiveExamples,
      negative_examples: profile.negativeExamples,
    }),
  })
  if (!res.ok) throw new Error('Failed to update category profile')
  return mapBackendCategoryProfile(await res.json())
}

export async function suggestCategoryProfile(
  categoryId: string,
  userGuidance: string,
): Promise<CategoryProfileDraft> {
  const res = await apiFetch(`/api/v1/taxonomy/categories/${categoryId}/profile/improve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_guidance: userGuidance }),
  })
  if (!res.ok) throw new Error('Failed to suggest category profile')
  return mapBackendCategoryProfileDraft(await res.json())
}

export async function createCategory(payload: {
  name: string
  parentId?: string | null
  description?: string | null
}): Promise<Folder> {
  const name = payload.name.trim()
  const res = await apiFetch('/api/v1/taxonomy/categories', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      parent_id: payload.parentId ?? null,
      slug: slugify(name),
      name,
      description: payload.description?.trim() || null,
      sort_order: 100,
    }),
  })
  if (!res.ok) throw new Error('Failed to create category')
  return mapBackendFolder(await res.json(), payload.parentId ?? null)
}

export async function updateCategory(
  categoryId: string,
  payload: { name?: string; description?: string | null },
): Promise<Folder> {
  const body: Record<string, string | null> = {}
  if (payload.name !== undefined) body.name = payload.name.trim()
  if (payload.description !== undefined) body.description = payload.description?.trim() || null
  const res = await apiFetch(`/api/v1/taxonomy/categories/${categoryId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error('Failed to update category')
  return mapBackendFolder(await res.json())
}

export async function archiveCategory(categoryId: string): Promise<void> {
  const res = await apiFetch(`/api/v1/taxonomy/categories/${categoryId}`, { method: 'DELETE', headers: { 'Content-Type': 'application/json' } })
  if (!res.ok) throw new Error('Failed to archive category')
}

export async function deleteCategory(
  categoryId: string,
  payload: {
    deleteNotes?: boolean
    confirmCategoryName?: string
    confirmDeleteNotesText?: string
  } = {},
): Promise<{
  archivedCategoriesCount: number
  movedNotesCount: number
  deletedNotesCount: number
}> {
  const res = await apiFetch(`/api/v1/taxonomy/categories/${categoryId}/delete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      delete_notes: payload.deleteNotes ?? false,
      confirm_category_name: payload.confirmCategoryName ?? null,
      confirm_delete_notes_text: payload.confirmDeleteNotesText ?? null,
    }),
  })
  if (!res.ok) throw new Error('Failed to delete category')
  const data = await res.json()
  return {
    archivedCategoriesCount: data.archived_categories_count ?? 0,
    movedNotesCount: data.moved_notes_count ?? 0,
    deletedNotesCount: data.deleted_notes_count ?? 0,
  }
}
