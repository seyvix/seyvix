import type { Note, NoteObject, SourceMetadata } from '../types'

export type SourceChip = {
  key: string
  providerLabel: string
  originLabel: string | null
  title: string
}

export type LinkChipModel = {
  key: string
  url: string
  label: string
  title: string
}

export type NoteDetailSourceModel = {
  provider: string
  providerLabel: string
  originLabel: string | null
  title: string
  href: string | null
  originalCreatedAt: string | null
}

export type NoteDetailObjectModel = {
  object: NoteObject
  index: number
  childHref: string | null
  viewerNoteId: string
}

export type NoteDetailModel = {
  source: NoteDetailSourceModel | null
  objects: NoteDetailObjectModel[]
}

export type TelegramCardModel = {
  sourceLabel: string
  originLabel: string | null
  caption: string | null
  media: NoteObject[]
  itemCount: number
}

const CARD_VISUAL_OBJECT_TYPES = new Set<NoteObject['type']>([
  'image',
  'video',
  'audio',
  'document',
  'link',
])

export function isCardVisualObjectType(type: NoteObject['type']): boolean {
  return CARD_VISUAL_OBJECT_TYPES.has(type)
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

export function getCardObjectAspectRatio(obj: NoteObject | undefined): number | null {
  const width = obj?.visualWidth ?? obj?.imageWidth
  const height = obj?.visualHeight ?? obj?.imageHeight
  if (!width || !height) return null
  return clamp(width / height, 0.68, 1.55)
}

function hasCardObjectAspectRatio(obj: NoteObject | undefined): boolean {
  return getCardObjectAspectRatio(obj) !== null
}

export function chooseCardRatioObject(objects: NoteObject[]): NoteObject | undefined {
  return objects.find(hasCardObjectAspectRatio) ?? objects[0]
}

export function chooseCompositeCardVisualObject(objects: NoteObject[]): NoteObject | undefined {
  const imageObj = objects.find(o => o.type === 'image')
  const videoObj = objects.find(o => o.type === 'video')
  const audioObj = objects.find(o => o.type === 'audio')
  const firstDoc = objects.find(o => o.type === 'document')
  const firstLink = objects.find(o => o.type === 'link')
  const firstLinkThumb = firstLink?.thumbnailUrl ?? null

  return chooseCardRatioObject([
    imageObj,
    videoObj,
    audioObj,
    firstDoc,
    firstLinkThumb ? firstLink : undefined,
  ].filter((obj): obj is NoteObject => Boolean(obj)))
}

export function getCompositePreviewObjects(objects: NoteObject[]): NoteObject[] {
  return objects.filter(obj => isCardVisualObjectType(obj.type)).slice(0, 5)
}

export function stripTelegramEmojiMarkers(text: string): string {
  return text.replace(/\{\{tg_emoji:[0-9]+\|([^}]+)\}\}/g, '$1')
}

const TITLE_LINK_RE = /\[([^\]]+)\]\([^)]+\)/g
const TITLE_INLINE_TAG_RE = /<\/?(?:u|b|i|s|em|strong|code|tg-spoiler)\b[^>]*>/gi
const TITLE_CUSTOM_EMOJI_RE = /\{\{tg_emoji:[0-9]+\|([^}]+)\}\}/g
const TITLE_MARKERS: Array<[RegExp, string]> = [
  [/^\s{0,3}#{1,6}\s+/g, ''],
  [/^\s{0,3}>\s+/g, ''],
  [/\*\*(.+?)\*\*/gs, '$1'],
  [/__(.+?)__/gs, '$1'],
  [/~~(.+?)~~/gs, '$1'],
  [/`+([^`]+?)`+/g, '$1'],
  [/(?<!\*)\*(?!\*)(\S(?:[^*\n]*?\S)?)\*(?!\*)/g, '$1'],
  [/(?<![A-Za-z0-9_])_(?!_)(\S(?:[^_\n]*?\S)?)_(?!_)(?![A-Za-z0-9_])/g, '$1'],
]

export function cleanDisplayTitle(value: string): string {
  let text = value.replace(/\r|\n/g, ' ')
  text = text.replace(TITLE_CUSTOM_EMOJI_RE, '$1')
  text = text.replace(TITLE_LINK_RE, '$1')
  text = text.replace(TITLE_INLINE_TAG_RE, '')
  for (const [pattern, replacement] of TITLE_MARKERS) {
    text = text.replace(pattern, replacement)
  }
  return text.replace(/\s+/g, ' ').trim()
}

function plainComparable(value: string): string {
  return stripTelegramEmojiMarkers(cleanDisplayTitle(value)).toLocaleLowerCase()
}

export function isRedundantTextTitle(title: string, text: string): boolean {
  const cleanTitle = plainComparable(title)
  const cleanText = plainComparable(text)
  if (!cleanTitle || !cleanText) return false
  return cleanText.length <= 240 && (cleanText === cleanTitle || cleanText.startsWith(`${cleanTitle} `))
}

function hasOddMarkerCount(text: string, marker: string): boolean {
  const matches = text.match(new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g'))
  return Boolean(matches && matches.length % 2 === 1)
}

export function truncateMarkdownInline(text: string, maxLength = 180): string {
  const normalized = text.replace(/\s+/g, ' ').trim()
  if (normalized.length <= maxLength) return normalized

  let truncated = normalized.slice(0, maxLength).trim()
  truncated = truncated.replace(/\{\{tg_emoji:[^}]*$/, '')
  if (hasOddMarkerCount(truncated, '**')) truncated += '**'
  if (hasOddMarkerCount(truncated, '__')) truncated += '__'
  if (hasOddMarkerCount(truncated, '`')) truncated += '`'
  return `${truncated}...`
}

function isTelegramTransportTitle(title: string): boolean {
  return /^telegram-(?:photo|image|video|voice|audio|document|file)(?:[-_][a-z0-9]+)*$/i.test(title)
}

export function getNoteDisplayTitle(note: Note, text?: string | null): string | null {
  const title = cleanDisplayTitle(note.title)
  if (!title) return null
  const isTelegram = note.source?.provider === 'telegram'
    || note.objects.some(obj => obj.source?.provider === 'telegram')
  if (isTelegram && isTelegramTransportTitle(title)) return null
  if (text && isRedundantTextTitle(title, text)) return null
  return title
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

export function collectLinkChips(note: Note): LinkChipModel[] {
  return note.objects
    .filter(obj => obj.type === 'link')
    .slice(0, 3)
    .map(obj => {
      let label = obj.content
      try {
        label = new URL(obj.content).hostname.replace(/^www\./, '')
      } catch {
        // keep original content as label
      }
      return {
        key: obj.id,
        url: obj.content,
        label,
        title: obj.content,
      }
    })
}

function firstSource(note: Note): SourceMetadata | null {
  return note.source ?? note.objects.find(obj => obj.source)?.source ?? null
}

export function getNoteDetailModel(note: Note): NoteDetailModel {
  const source = firstSource(note)
  const sourceOrigin = source ? sourceOriginLabel(source) : null
  return {
    source: source
      ? {
          provider: source.provider,
          providerLabel: source.providerLabel || source.provider,
          originLabel: sourceOrigin,
          title: sourceOrigin ? `${source.providerLabel || source.provider}: ${sourceOrigin}` : source.providerLabel || source.provider,
          href: source.url ?? null,
          originalCreatedAt: source.originalCreatedAt ?? null,
        }
      : null,
    objects: note.objects.map((object, index) => {
      const childHref = note.type === 'collection' && object.slug ? `/notes/${object.slug}` : null
      return {
        object,
        index,
        childHref,
        viewerNoteId: childHref ? (object.noteId ?? object.id) : note.id,
      }
    }),
  }
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
