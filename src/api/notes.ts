import type { Note, NotesParams } from '../types'

export async function fetchNotes(params: NotesParams = {}): Promise<Note[]> {
  const url = new URL('/api/notes', window.location.origin)
  if (params.search) url.searchParams.set('search', params.search)
  if (params.tags?.length) url.searchParams.set('tags', params.tags.join(','))
  if (params.folders?.length) url.searchParams.set('folders', params.folders.join(','))

  const res = await fetch(url)
  if (!res.ok) throw new Error('Failed to fetch notes')
  return res.json() as Promise<Note[]>
}

export async function fetchNote(slug: string): Promise<Note> {
  const res = await fetch(`/api/notes/${slug}`)
  if (!res.ok) throw new Error('Failed to fetch note')
  return res.json() as Promise<Note>
}

export async function createNote(data: Partial<Note>): Promise<Note> {
  const res = await fetch('/api/notes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to create note')
  return res.json() as Promise<Note>
}

export async function addFilesToNote(noteId: string, files: File[]): Promise<Note> {
  const formData = new FormData()
  formData.append('noteId', noteId)
  files.forEach(f => formData.append('files', f))
  const res = await fetch('/api/notes/add-files', { method: 'POST', body: formData })
  if (!res.ok) throw new Error('Failed to add files to note')
  return res.json() as Promise<Note>
}

export async function uploadFiles(files: File[]): Promise<Note> {
  const formData = new FormData()
  files.forEach(f => formData.append('files', f))
  const res = await fetch('/api/notes/upload', { method: 'POST', body: formData })
  if (!res.ok) throw new Error('Failed to upload files')
  return res.json() as Promise<Note>
}

export async function mergeNotes(sourceId: string, targetId: string): Promise<{ updated: Note; removedId: string }> {
  const res = await fetch('/api/notes/merge', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sourceId, targetId }),
  })
  if (!res.ok) throw new Error('Failed to merge notes')
  return res.json()
}

export async function updateNote(slug: string, data: Partial<Note>): Promise<Note> {
  const res = await fetch(`/api/notes/${slug}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to update note')
  return res.json() as Promise<Note>
}
