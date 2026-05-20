import type { Note, NoteObject, SourceMetadata } from '../types'

export type SourceChip = {
  key: string
  providerLabel: string
  originLabel: string | null
  title: string
}

export type TelegramCardModel = {
  sourceLabel: string
  originLabel: string | null
  caption: string | null
  media: NoteObject[]
  itemCount: number
}

export function stripTelegramEmojiMarkers(text: string): string {
  return text.replace(/\{\{tg_emoji:[0-9]+\|([^}]+)\}\}/g, '$1')
}

function sourceText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

export function sourceOriginLabel(source: SourceMetadata): string | null {
  const origin = source.origin
  if (!origin) return sourceText(source.title)
  const title = sourceText(origin.title)
  const name = sourceText(origin.name)
  const username = sourceText(origin.username)
  return title ?? name ?? username ?? sourceText(source.title)
}

export function collectSourceChips(note: Note): SourceChip[] {
  const sources = [
    note.source,
    ...note.objects.map(obj => obj.source),
  ].filter((source): source is SourceMetadata => Boolean(source))
  const chips = new Map<string, SourceChip>()

  for (const source of sources) {
    const providerLabel = source.providerLabel || source.provider
    const originLabel = sourceOriginLabel(source)
    const key = `${source.provider}:${originLabel ?? source.externalId}`
    if (chips.has(key)) continue
    chips.set(key, {
      key,
      providerLabel,
      originLabel,
      title: originLabel ? `${providerLabel}: ${originLabel}` : providerLabel,
    })
  }

  return Array.from(chips.values()).slice(0, 3)
}

function firstSource(note: Note): SourceMetadata | null {
  return note.source ?? note.objects.find(obj => obj.source)?.source ?? null
}

function cleanPreviewText(value: string | null | undefined): string | null {
  const text = stripTelegramEmojiMarkers(value ?? '').trim()
  return text.length > 0 ? text : null
}

export function getTelegramCardModel(note: Note): TelegramCardModel | null {
  const source = firstSource(note)
  if (!source || source.provider !== 'telegram') return null

  const captionObject = note.objects.find(obj => cleanPreviewText(obj.caption))
  const textObject = note.objects.find(obj => obj.type === 'text' && cleanPreviewText(obj.content))
  const caption = cleanPreviewText(captionObject?.caption)
    ?? cleanPreviewText(textObject?.content)
    ?? cleanPreviewText(note.title)

  return {
    sourceLabel: source.providerLabel || 'Telegram',
    originLabel: sourceOriginLabel(source),
    caption,
    media: note.objects.filter(obj => obj.type === 'image' || obj.type === 'audio' || obj.type === 'video' || obj.type === 'document'),
    itemCount: note.objects.length,
  }
}

function startOfLocalDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate())
}

export function getSavedDateLabel(value: string, now = new Date()): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''

  const dayMs = 24 * 60 * 60 * 1000
  const diffDays = Math.round((startOfLocalDay(now).getTime() - startOfLocalDay(date).getTime()) / dayMs)

  if (diffDays === 0) return 'Сегодня'
  if (diffDays === 1) return 'Вчера'
  if (diffDays > 1 && diffDays < 7) return `${diffDays} дн. назад`

  return new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric',
    month: 'short',
    ...(date.getFullYear() !== now.getFullYear() ? { year: 'numeric' } : {}),
  }).format(date).replace('.', '')
}
