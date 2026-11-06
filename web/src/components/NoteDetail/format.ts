import type { Note, NoteObject, RecommendedNote, SourceMetadata } from '../../types'

const DETAIL_DATE_FORMAT = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

export function formatDetailDate(value: string | null | undefined): string | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : DETAIL_DATE_FORMAT.format(date)
}

export function formatBytes(bytes?: number): string {
  if (!bytes) return '0 KB'
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function formatMediaTime(value: number): string {
  if (!Number.isFinite(value) || value < 0) return '0:00'
  const totalSeconds = Math.floor(value)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = String(totalSeconds % 60).padStart(2, '0')
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${seconds}` : `${minutes}:${seconds}`
}

export function baseFileName(filename?: string | null): string {
  return filename ? filename.replace(/\.[^.]+$/, '') : 'Документ'
}

export function linkDomain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

function sourceText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

/** "Channel title @username" style origin label for a source. */
export function sourceOriginLabel(source: SourceMetadata): string | null {
  const origin = source.origin
  if (!origin) return null
  const username = sourceText(origin.username)
  const base = sourceText(origin.title) ?? sourceText(origin.name) ?? username
  if (!base) return null
  return username && username !== base ? `${base} @${username}` : base
}

export function primarySource(note: Note, objects: NoteObject[]): SourceMetadata | null {
  return note.source ?? objects.find(obj => obj.source)?.source ?? null
}

export function objectDomId(id: string): string {
  return `note-object-${id.replace(/[^a-zA-Z0-9_-]/g, '-')}`
}

export function noteTypeLabel(type: Note['type']): string {
  if (type === 'collection') return 'Коллекция'
  if (type === 'composite') return 'Составная заметка'
  return 'Заметка'
}

const OBJECT_KIND_LABEL: Record<NoteObject['type'], string> = {
  text: 'Текст',
  image: 'Изображение',
  link: 'Ссылка',
  document: 'Документ',
  audio: 'Аудио',
  video: 'Видео',
}

export function objectKindLabel(type: NoteObject['type']): string {
  return OBJECT_KIND_LABEL[type]
}

export function objectNavTitle(obj: NoteObject, index: number): string {
  if (obj.type === 'text') {
    const firstLine = obj.content.split('\n').find(line => line.trim())?.trim()
    return firstLine ? firstLine.replace(/^#+\s*/, '').slice(0, 64) : `Текст ${index + 1}`
  }
  if (obj.type === 'link') return linkDomain(obj.content).slice(0, 64)
  if (obj.caption?.trim()) return obj.caption.trim().slice(0, 64)
  return obj.filename ?? `${objectKindLabel(obj.type)} ${index + 1}`
}

export function recommendedNoteTypeLabel(note: RecommendedNote): string {
  if (note.type !== 'simple') return noteTypeLabel(note.type)
  return note.mediaType ? objectKindLabel(note.mediaType) : 'Заметка'
}

export function recommendationScoreLabel(score: number): string {
  if (!Number.isFinite(score)) return ''
  return `${Math.round(Math.max(0, Math.min(score, 1)) * 100)}%`
}

const OBJECT_COUNT_ORDER: NoteObject['type'][] = ['text', 'image', 'link', 'document', 'audio', 'video']

export function objectCountSummary(objects: NoteObject[]): Array<{ type: NoteObject['type']; count: number }> {
  const counts = new Map<NoteObject['type'], number>()
  for (const obj of objects) counts.set(obj.type, (counts.get(obj.type) ?? 0) + 1)
  return OBJECT_COUNT_ORDER
    .filter(type => counts.has(type))
    .map(type => ({ type, count: counts.get(type)! }))
}

// ─── Background job statuses ──────────────────────────────────────────────────
// Snapshot jobs: pending | processing | done | failed | cancelled.
// Tag / taxonomy jobs: pending | processing | succeeded | failed | cancelled.

export function isActiveJob(job: { status: string }): boolean {
  return job.status === 'pending' || job.status === 'processing'
}

export function isFinishedJob(job: { status: string }): boolean {
  return job.status === 'done' || job.status === 'succeeded' || job.status === 'completed'
}

export function jobStatusLabel(job: { status: string }): string {
  if (isFinishedJob(job)) return 'Готово'
  if (job.status === 'failed') return 'Ошибка'
  if (job.status === 'cancelled') return 'Пропущено'
  if (job.status === 'processing') return 'Обработка'
  return 'В очереди'
}

/** Slow job-status polling: results arrive via the change feed; this only refreshes progress. */
export const JOB_PROGRESS_POLL_MS = 10_000
