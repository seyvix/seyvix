import type { NoteObject } from '../types'

export function getObjectPreviewSource(obj: NoteObject): string {
  return obj.thumbnailUrl || obj.cover || obj.content
}

export function getObjectDisplayText(obj: NoteObject, maxLength = 180): string {
  const text = obj.thumbnailText || obj.content
  if (text.length <= maxLength) return text
  return `${text.slice(0, maxLength).trim()}...`
}
