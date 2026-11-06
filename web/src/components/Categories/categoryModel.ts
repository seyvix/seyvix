import type { CategoryProfile, CategoryProfileDraft, Folder, FolderNoteSummary, NoteObject } from '../../types'
import { cleanDisplayTitle } from '../../utils/noteCardPresentation'
import { getObjectPreviewSource } from '../../utils/notePreview'

export const INBOX_PATH = 'inbox'

export function categoryUrl(path: string): string {
  return `/categories/${path.split('/').map(encodeURIComponent).join('/')}`
}

export function categoryNotesUrl(path: string): string {
  return `/notes?folders=${encodeURIComponent(path)}`
}

export function countCategories(categories: Folder[]): number {
  return categories.reduce((total, category) => total + 1 + countCategories(category.children), 0)
}

export function findCategory(categories: Folder[], path: string): Folder | null {
  for (const category of categories) {
    if (category.path === path) return category
    const child = findCategory(category.children, path)
    if (child) return child
  }
  return null
}

export function ancestorPaths(path: string): string[] {
  const segments = path.split('/').filter(Boolean)
  return segments.slice(0, -1).map((_, index) => segments.slice(0, index + 1).join('/'))
}

// ─── Profile form ─────────────────────────────────────────────────────────────

export interface CategoryProfileForm {
  summary: string
  keywords: string
  positiveExamples: string
  negativeExamples: string
}

export type CategoryProfileInput = Pick<CategoryProfile, 'summary' | 'keywords' | 'positiveExamples' | 'negativeExamples'>

export const EMPTY_PROFILE_FORM: CategoryProfileForm = { summary: '', keywords: '', positiveExamples: '', negativeExamples: '' }

function textToList(value: string): string[] {
  return value.split(/\n|,/).map(item => item.trim()).filter(Boolean)
}

export function profileFormFrom(profile: CategoryProfile | CategoryProfileDraft | undefined): CategoryProfileForm {
  return {
    summary: profile?.summary ?? '',
    keywords: (profile?.keywords ?? []).join('\n'),
    positiveExamples: (profile?.positiveExamples ?? []).join('\n'),
    negativeExamples: (profile?.negativeExamples ?? []).join('\n'),
  }
}

export function formToProfile(form: CategoryProfileForm): CategoryProfileInput {
  return {
    summary: form.summary.trim() || null,
    keywords: textToList(form.keywords),
    positiveExamples: textToList(form.positiveExamples),
    negativeExamples: textToList(form.negativeExamples),
  }
}

export function hasProfileFormContent(form: CategoryProfileForm): boolean {
  return Object.values(form).some(value => value.trim())
}

export function profileFromDraft(draft: CategoryProfileDraft): CategoryProfileInput {
  return {
    summary: draft.summary,
    keywords: draft.keywords,
    positiveExamples: draft.positiveExamples,
    negativeExamples: draft.negativeExamples,
  }
}

// ─── Note rows ────────────────────────────────────────────────────────────────

const NOTE_DATE_FORMAT = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short' })
const NOTE_DATE_WITH_YEAR_FORMAT = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' })

export function formatCategoryNoteDate(note: FolderNoteSummary): string {
  const date = new Date(note.updatedAt || note.createdAt)
  if (Number.isNaN(date.getTime())) return 'Дата неизвестна'
  return (date.getFullYear() === new Date().getFullYear() ? NOTE_DATE_FORMAT : NOTE_DATE_WITH_YEAR_FORMAT).format(date)
}

export function cleanPreviewText(value: string): string {
  const withoutImages = value.replace(/!\[([^\]]*)\]\([^)]+\)/g, (_match, alt: string) => (
    alt.trim().toLowerCase() === 'favicon' ? '' : alt
  ))
  return cleanDisplayTitle(withoutImages).replace(/\\(\S)/g, '$1').replace(/\s+/g, ' ').trim()
}

export function noteTextPreview(note: FolderNoteSummary): string | null {
  const object = note.objects.find(obj => obj.type === 'text' || obj.thumbnailText || obj.caption)
  if (!object) return null
  const text = cleanPreviewText(object.thumbnailText || object.caption || object.content)
  if (!text) return null
  return text.length <= 110 ? text : `${text.slice(0, 110).trim()}...`
}

export function noteVisualObject(note: FolderNoteSummary): NoteObject | null {
  return note.objects.find(obj => (
    (obj.type === 'image' && getObjectPreviewSource(obj))
    || (obj.type === 'video' && obj.thumbnailUrl)
    || (obj.type === 'document' && (obj.thumbnailUrl || obj.cover))
    || (obj.type === 'link' && obj.thumbnailUrl)
  )) ?? null
}
