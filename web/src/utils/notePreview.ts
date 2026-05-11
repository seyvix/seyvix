import type { NoteObject } from '../types'

export function getObjectPreviewSource(obj: NoteObject): string {
  return obj.thumbnailUrl || obj.cover || obj.content
}

export function getObjectDisplayText(obj: NoteObject, maxLength = 180): string {
  const text = (obj.thumbnailText || obj.content).replace(
    /\{\{tg_emoji:[0-9]+\|([^}]+)\}\}/g,
    '$1',
  )
  if (text.length <= maxLength) return text
  return `${text.slice(0, maxLength).trim()}...`
}
