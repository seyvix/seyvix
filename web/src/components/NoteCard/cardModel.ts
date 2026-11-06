import type { CSSProperties } from 'react'
import type { Note, NoteObject } from '../../types'
import { getCardObjectAspectRatio } from '../../utils/noteCardPresentation'

const FALLBACK_COLORS = ['#1e3a2a', '#1e2a3a', '#2e1e3a', '#3a2e1e']

export type TextDensity = 'short' | 'medium' | 'long'

export function notePageHref(note: Note): string {
  if (note.isLocal || note.isLoading) return '/notes'
  return `/notes/${note.id}`
}

export function textDensity(text: string | null | undefined): TextDensity {
  const length = (text ?? '').trim().length
  if (length < 90) return 'short'
  if (length > 280) return 'long'
  return 'medium'
}

export function fallbackColor(noteId: string): string {
  return FALLBACK_COLORS[noteId.charCodeAt(0) % FALLBACK_COLORS.length]
}

export function visualRatioStyle(obj: NoteObject | undefined, fallbackRatio: number): CSSProperties {
  return { '--note-card-visual-ratio': String(getCardObjectAspectRatio(obj) ?? fallbackRatio) } as CSSProperties
}

export function intrinsicRatioStyle(obj: NoteObject | undefined): CSSProperties | undefined {
  return obj?.imageWidth && obj.imageHeight ? { aspectRatio: `${obj.imageWidth}/${obj.imageHeight}` } : undefined
}

export function documentThumb(obj: NoteObject | undefined): string | null {
  return obj ? (obj.thumbnailUrl ?? obj.cover ?? null) : null
}

export function isUrlOnlyText(obj: NoteObject | undefined): boolean {
  return Boolean(obj && /^https?:\/\//.test(obj.content))
}

/** One pass over the objects instead of a `find` per media type. */
export function firstObjectsByType(objects: NoteObject[]): Partial<Record<NoteObject['type'], NoteObject>> {
  const first: Partial<Record<NoteObject['type'], NoteObject>> = {}
  for (const obj of objects) {
    if (!first[obj.type]) first[obj.type] = obj
  }
  return first
}

export function fileExtension(label: string): string {
  return label.includes('.') ? label.split('.').pop()!.toUpperCase().slice(0, 4) : 'FILE'
}
