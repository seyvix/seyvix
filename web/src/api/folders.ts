import { apiFetch } from '../lib/apiClient.ts'
import type { Folder, FolderDetail, FolderNoteSummary, Tag } from '../types'

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

function encodeFolderPath(path: string): string {
  return path.split('/').map(encodeURIComponent).join('/')
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
  const res = await apiFetch('/api/v1/taxonomy/content/inbox/reclassify', { method: 'POST' })
  if (!res.ok) throw new Error('Failed to reclassify inbox')
  const data = await res.json()
  return { enqueuedCount: data.enqueued_count ?? 0 }
}
