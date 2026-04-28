import { apiFetch } from '../lib/apiClient'
import type { Folder } from '../types'

const BASE = '/api/v1/folders'

export async function fetchFolders(): Promise<Folder[]> {
  const res = await apiFetch(BASE)
  if (!res.ok) throw new Error('Failed to fetch folders')
  return res.json() as Promise<Folder[]>
}

export async function fetchFolder(slug: string): Promise<Folder> {
  const res = await apiFetch(`${BASE}/${slug}`)
  if (!res.ok) throw new Error('Failed to fetch folder')
  return res.json() as Promise<Folder>
}
