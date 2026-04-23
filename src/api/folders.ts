import type { Folder } from '../types'

export async function fetchFolders(): Promise<Folder[]> {
  const res = await fetch('/api/folders')
  if (!res.ok) throw new Error('Failed to fetch folders')
  return res.json() as Promise<Folder[]>
}

export async function fetchFolder(slug: string): Promise<Folder> {
  const res = await fetch(`/api/folders/${slug}`)
  if (!res.ok) throw new Error('Failed to fetch folder')
  return res.json() as Promise<Folder>
}
