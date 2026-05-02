import { apiFetch } from '../lib/apiClient'
import type { Folder } from '../types'

const BASE = '/api/v1/folders'

// Backend shape from FolderTreeResponse / FolderTreeItem
interface BackendFolderItem {
  id: string
  name: string
  slug: string
  path: string
  children?: BackendFolderItem[]
}

function mapFolder(item: BackendFolderItem, parentId: string | null = null): Folder {
  return {
    id: item.id,
    slug: item.slug,
    name: item.name,
    parentId,
    children: (item.children ?? []).map(c => mapFolder(c, item.id)),
  }
}

export async function fetchFolders(): Promise<Folder[]> {
  const res = await apiFetch(BASE)
  if (!res.ok) throw new Error('Failed to fetch folders')
  const data = await res.json()
  // Backend returns { items: FolderTreeItem[] }
  const items: BackendFolderItem[] = Array.isArray(data) ? data : (data.items ?? [])
  return items.map(item => mapFolder(item))
}

export async function fetchFolder(slug: string): Promise<Folder> {
  const res = await apiFetch(`${BASE}/${slug}`)
  if (!res.ok) throw new Error('Failed to fetch folder')
  const data = await res.json()
  // Backend returns FolderDetailResponse: { folder, tags, notes }
  return mapFolder(data.folder ?? data)
}
