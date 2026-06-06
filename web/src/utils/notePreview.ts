import type { NoteObject } from '../types'
import { stripTelegramEmojiMarkers, truncateMarkdownInline } from './noteCardPresentation.ts'

export function getObjectPreviewSource(obj: NoteObject): string {
  return obj.thumbnailUrl || obj.cover || obj.content
}

export function getObjectDisplayText(obj: NoteObject, maxLength = 180): string {
  const text = stripTelegramEmojiMarkers(obj.thumbnailText || obj.content)
  if (text.length <= maxLength) return text
  return `${text.slice(0, maxLength).trim()}...`
}

export function getObjectDisplayMarkdown(obj: NoteObject, maxLength = 180): string {
  return truncateMarkdownInline(obj.thumbnailText || obj.content, maxLength)
}
