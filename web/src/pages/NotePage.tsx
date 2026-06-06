import { useState, useEffect } from 'react'
import type { ReactNode } from 'react'
import PDFViewer from '../components/PDFViewer/PDFViewer'
import { useFavicon } from '../hooks/useFavicon'
import { Link, useParams, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowLeft,
  CalendarDays,
  ExternalLink,
  File,
  FileText,
  FileDown,
  Globe,
  Download,
  RefreshCw,
  X,
  Check,
  Clock3,
  FolderTree,
  Image as ImageIcon,
  Layers3,
  Link2,
  Mic2,
  Plus,
  Search,
  Send,
  Tag as TagIcon,
  Trash2,
  Type,
  Video,
} from 'lucide-react'
import { useNote } from '../hooks/useNote'
import { useUpdateNote } from '../hooks/useUpdateNote'
import { useRemoveCollectionItems } from '../hooks/useRemoveCollectionItems'
import { getTagColor } from '../utils/tagColor'
import { getObjectPreviewSource } from '../utils/notePreview'
import { getTelegramCardModel, type TelegramCardModel } from '../utils/noteCardPresentation'
import { parseMarkdownBlocks, type MarkdownBlock } from '../utils/markdownBlocks'
import AuthImage from '../components/AuthImage/AuthImage'
import HtmlSnapshotViewer from '../components/HtmlSnapshotViewer/HtmlSnapshotViewer'
import { LoaderSpinner } from '../components/LoaderSpinner'
import { apiFetch } from '../lib/apiClient'
import { deleteNotes } from '../api/notes'
import { useAuthenticatedObjectUrl } from '../hooks/useAuthenticatedObjectUrl'
import {
  acceptTagSuggestion,
  acceptTaxonomyAssignment,
  assignCategoryToContent,
  assignExistingTagToContent,
  createTaxonomyCategory,
  createOrFindTag,
  fetchContentTagSuggestions,
  fetchContentTagJobs,
  fetchContentTags,
  fetchSnapshotArtifacts,
  fetchSnapshotJobs,
  fetchTaxonomyAssignments,
  fetchTaxonomyClassificationJobs,
  rejectTagSuggestion,
  rejectTaxonomyAssignment,
  reprocessSnapshotMarkdown,
  searchTaxonomyCategories,
  type ContentTagAssignment,
  type ContentTagJob,
  type SnapshotArtifact,
  type SnapshotJob,
  type TaxonomyAssignment,
  type TaxonomyClassificationJob,
} from '../api/enrichment'
import type { Note, NoteObject, SnapshotView, SourceMetadata, Tag } from '../types'
import styles from './NotePage.module.css'

// ─── Helpers ───────────────────────────────────────────────────────────────────

function getExt(filename?: string): string {
  if (!filename) return 'FILE'
  const parts = filename.split('.')
  return parts.length > 1 ? parts.pop()!.toUpperCase() : 'FILE'
}

function getBaseName(filename?: string): string {
  if (!filename) return 'Документ'
  return filename.replace(/\.[^.]+$/, '')
}

function sourceTextValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function sourceOriginLabel(source: SourceMetadata): string | null {
  const origin = source.origin
  if (!origin) return null
  const title = sourceTextValue(origin.title)
  const name = sourceTextValue(origin.name)
  const username = sourceTextValue(origin.username)
  const base = title ?? name ?? username
  if (!base) return null
  return username && username !== base ? `${base} @${username}` : base
}

function sourceLabel(source: SourceMetadata): string {
  const origin = sourceOriginLabel(source)
  return origin ? `${source.providerLabel} · ${origin}` : source.providerLabel
}

function ObjectSource({ source }: { source?: SourceMetadata | null }) {
  if (!source) return null
  const label = sourceLabel(source)
  const children = (
    <>
      <Send size={12} />
      <span>{label}</span>
      {source.url && <ExternalLink size={11} />}
    </>
  )
  if (source.url) {
    return (
      <a className={styles.sourceMeta} href={source.url} target="_blank" rel="noreferrer">
        {children}
      </a>
    )
  }
  return <div className={styles.sourceMeta}>{children}</div>
}

function notePrimarySource(note: Note, objects: NoteObject[]): SourceMetadata | null {
  return note.source ?? objects.find(obj => obj.source)?.source ?? null
}

function sourceDateLabel(source?: SourceMetadata | null): string | null {
  if (!source?.originalCreatedAt) return null
  const date = new Date(source.originalCreatedAt)
  if (Number.isNaN(date.getTime())) return null
  return date.toLocaleString('ru-RU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatDetailDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'нет даты'
  return date.toLocaleString('ru-RU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function objectDomId(id: string): string {
  return `note-object-${id.replace(/[^a-zA-Z0-9_-]/g, '-')}`
}

function noteTypeLabel(note: Note): string {
  if (note.type === 'collection') return 'Коллекция'
  if (note.type === 'composite') return 'Составная заметка'
  return 'Заметка'
}

function objectKindLabel(type: NoteObject['type']): string {
  if (type === 'text') return 'Текст'
  if (type === 'image') return 'Изображение'
  if (type === 'link') return 'Ссылка'
  if (type === 'document') return 'Документ'
  if (type === 'audio') return 'Аудио'
  return 'Видео'
}

function objectKindIcon(type: NoteObject['type']) {
  if (type === 'text') return <Type size={14} />
  if (type === 'image') return <ImageIcon size={14} />
  if (type === 'link') return <Link2 size={14} />
  if (type === 'document') return <File size={14} />
  if (type === 'audio') return <Mic2 size={14} />
  return <Video size={14} />
}

function objectNavTitle(obj: NoteObject, index: number): string {
  if (obj.type === 'text') {
    const firstLine = obj.content.split('\n').find(line => line.trim())?.trim()
    return firstLine ? firstLine.replace(/^#+\s*/, '').slice(0, 64) : `Текст ${index + 1}`
  }
  if (obj.type === 'link') {
    try {
      return new URL(obj.content).hostname.replace(/^www\./, '')
    } catch {
      return obj.content.slice(0, 64)
    }
  }
  if (obj.caption?.trim()) return obj.caption.trim().slice(0, 64)
  if (obj.filename) return obj.filename
  return `${objectKindLabel(obj.type)} ${index + 1}`
}

function objectCountSummary(objects: NoteObject[]): Array<{ type: NoteObject['type']; count: number }> {
  const order: NoteObject['type'][] = ['text', 'image', 'link', 'document', 'audio', 'video']
  const counts = new Map<NoteObject['type'], number>()
  objects.forEach(obj => counts.set(obj.type, (counts.get(obj.type) ?? 0) + 1))
  return order
    .map(type => ({ type, count: counts.get(type) ?? 0 }))
    .filter(item => item.count > 0)
}

async function authDownload(url: string, filename?: string) {
  try {
    const res = await apiFetch(url)
    if (!res.ok) return
    const blob = await res.blob()
    const objectUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = objectUrl
    a.download = filename ?? url.split('/').pop() ?? 'download'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(objectUrl)
  } catch { /* ignore */ }
}

// ─── Doc blob cache (preload before DocViewer mounts) ──────────────────────────

const docBlobCache = new Map<string, string>()

function prefetchDocBlob(url: string) {
  if (docBlobCache.has(url)) return
  apiFetch(url)
    .then(r => r.blob())
    .then(blob => { docBlobCache.set(url, URL.createObjectURL(blob)) })
    .catch(() => {})
}

// ─── Tags ──────────────────────────────────────────────────────────────────────

function TagList({ tags }: { tags: Tag[] }) {
  if (tags.length === 0) return null
  return (
    <>
      {tags.map(tag => {
        const { bg, text } = getTagColor(tag.name)
        return (
          <span key={tag.id} className={styles.tag} style={{ background: bg, color: text }}>
            {tag.name}
          </span>
        )
      })}
    </>
  )
}

function NoteOverview({ note, objects }: { note: Note; objects: NoteObject[] }) {
  const source = notePrimarySource(note, objects)
  const sourceDate = sourceDateLabel(source)
  const counts = objectCountSummary(objects)

  return (
    <div className={styles.overviewPanel}>
      <div className={styles.overviewHeader}>
        <span>{noteTypeLabel(note)}</span>
        <strong>{objects.length}</strong>
      </div>

      <div className={styles.overviewFacts}>
        <div className={styles.overviewFact}>
          <CalendarDays size={14} />
          <div>
            <span>Создано</span>
            <strong>{formatDetailDate(note.createdAt)}</strong>
          </div>
        </div>
        <div className={styles.overviewFact}>
          <Clock3 size={14} />
          <div>
            <span>Изменено</span>
            <strong>{formatDetailDate(note.updatedAt)}</strong>
          </div>
        </div>
        {source && (
          <div className={styles.overviewFact}>
            <Send size={14} />
            <div>
              <span>{source.providerLabel}</span>
              {source.url ? (
                <a href={source.url} target="_blank" rel="noreferrer">
                  {sourceOriginLabel(source) ?? source.url}
                  <ExternalLink size={11} />
                </a>
              ) : (
                <strong>{sourceOriginLabel(source) ?? 'Источник'}</strong>
              )}
              {sourceDate && <small>{sourceDate}</small>}
            </div>
          </div>
        )}
      </div>

      {counts.length > 0 && (
        <div className={styles.objectCounts}>
          {counts.map(item => (
            <span key={item.type} title={objectKindLabel(item.type)}>
              {objectKindIcon(item.type)}
              {item.count}
            </span>
          ))}
        </div>
      )}

      {objects.length > 1 && (
        <nav className={styles.objectNav} aria-label="Содержимое заметки">
          <div className={styles.objectNavTitle}>
            <Layers3 size={14} />
            <span>Содержимое</span>
          </div>
          {objects.map((obj, index) => (
            <a key={obj.id} href={`#${objectDomId(obj.id)}`}>
              {objectKindIcon(obj.type)}
              <span>{objectNavTitle(obj, index)}</span>
            </a>
          ))}
        </nav>
      )}
    </div>
  )
}

function formatBytes(bytes?: number): string {
  if (!bytes) return '0 KB'
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function enrichmentJobStatusLabel(job: ContentTagJob | TaxonomyClassificationJob): string {
  if (job.status === 'completed' || job.status === 'done') return 'Готово'
  if (job.status === 'failed') return 'Ошибка'
  if (job.status === 'processing') return 'Обработка'
  return 'В очереди'
}

function isActiveJob(job: { status: string }) {
  return job.status !== 'completed' && job.status !== 'done' && job.status !== 'failed'
}


const SNAPSHOT_ICON: Record<string, React.ReactNode> = {
  markdown: <FileText size={12} />,
  pdf:      <FileDown  size={12} />,
  html:     <Globe     size={12} />,
}

function customEmojiAssets(source?: NoteObject['source'] | null): Record<string, { data_url?: string; fallback?: string }> {
  const assets = source?.metadata?.custom_emoji_assets
  return assets && typeof assets === 'object' && !Array.isArray(assets)
    ? assets as Record<string, { data_url?: string; fallback?: string }>
    : {}
}

function renderInlineMarkdown(text: string, source: NoteObject['source'] | null | undefined, keyPrefix: string): ReactNode[] {
  const pattern = /!\[favicon\]\(([^)]+)\)\s+\[([^\]]+)\]\(([^)]+)\)|\{\{tg_emoji:([0-9]+)\|([^}]+)\}\}|!\[([^\]]*)\]\(([^)]+)\)|\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*|__([^_]+)__|`([^`]+)`|<u>(.*?)<\/u>|_([^_\n]+)_/g
  const emojiAssets = customEmojiAssets(source)
  const parts: ReactNode[] = []
  let lastIndex = 0

  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0
    if (index > lastIndex) {
      parts.push(text.slice(lastIndex, index))
    }
    const [
      ,
      faviconUrl,
      faviconLabel,
      faviconHref,
      customEmojiId,
      fallback,
      imageAlt,
      imageHref,
      linkLabel,
      linkHref,
      boldText,
      boldAltText,
      codeText,
      underlineText,
      italicText,
    ] = match
    if (customEmojiId) {
      const asset = emojiAssets[customEmojiId]
      parts.push(
        asset?.data_url ? (
          <img
            key={`${keyPrefix}-emoji-${customEmojiId}-${index}`}
            className={styles.inlineTelegramEmoji}
            src={asset.data_url}
            alt={asset.fallback || fallback}
            title={customEmojiId}
          />
        ) : (
          <span key={`${keyPrefix}-emoji-fallback-${customEmojiId}-${index}`} title={customEmojiId}>{fallback}</span>
        )
      )
    } else if (faviconHref) {
      parts.push(
        <a
          key={`${keyPrefix}-favicon-${faviconHref}-${index}`}
          className={styles.inlineMarkdownLink}
          href={faviconHref}
          target="_blank"
          rel="noopener noreferrer"
        >
          <img src={faviconUrl} alt="" />
          <span>{faviconLabel}</span>
        </a>
      )
    } else if (imageHref) {
      parts.push(
        <a
          key={`${keyPrefix}-image-${imageHref}-${index}`}
          className={styles.inlineMarkdownAttachment}
          href={imageHref}
          target="_blank"
          rel="noopener noreferrer"
        >
          {imageAlt || imageHref}
        </a>
      )
    } else if (linkHref) {
      parts.push(
        <a
          key={`${keyPrefix}-link-${linkHref}-${index}`}
          href={linkHref}
          target="_blank"
          rel="noopener noreferrer"
        >
          {linkLabel}
        </a>
      )
    } else if (boldText || boldAltText) {
      const value = boldText ?? boldAltText
      parts.push(<strong key={`${keyPrefix}-bold-${index}`}>{renderInlineMarkdown(value, source, `${keyPrefix}-bold-${index}`)}</strong>)
    } else if (codeText) {
      parts.push(<code key={`${keyPrefix}-code-${index}`}>{codeText}</code>)
    } else if (underlineText) {
      parts.push(<u key={`${keyPrefix}-underline-${index}`}>{renderInlineMarkdown(underlineText, source, `${keyPrefix}-underline-${index}`)}</u>)
    } else if (italicText) {
      parts.push(<em key={`${keyPrefix}-italic-${index}`}>{renderInlineMarkdown(italicText, source, `${keyPrefix}-italic-${index}`)}</em>)
    }
    lastIndex = index + match[0].length
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }

  return parts
}

function MarkdownBlockView({ block, source, index }: { block: MarkdownBlock; source?: NoteObject['source'] | null; index: number }) {
  const keyPrefix = `md-${index}`
  if (block.type === 'heading') {
    const Tag = `h${block.level}` as 'h1' | 'h2' | 'h3'
    return <Tag>{renderInlineMarkdown(block.text, source, keyPrefix)}</Tag>
  }
  if (block.type === 'paragraph') {
    return <p>{renderInlineMarkdown(block.text, source, keyPrefix)}</p>
  }
  if (block.type === 'blockquote') {
    return <blockquote>{renderInlineMarkdown(block.text, source, keyPrefix)}</blockquote>
  }
  if (block.type === 'bulletList') {
    return (
      <ul>
        {block.items.map((item, itemIndex) => (
          <li key={itemIndex}>{renderInlineMarkdown(item, source, `${keyPrefix}-li-${itemIndex}`)}</li>
        ))}
      </ul>
    )
  }
  if (block.type === 'orderedList') {
    return (
      <ol>
        {block.items.map((item, itemIndex) => (
          <li key={itemIndex}>{renderInlineMarkdown(item, source, `${keyPrefix}-li-${itemIndex}`)}</li>
        ))}
      </ol>
    )
  }
  if (block.type === 'taskList') {
    return (
      <ul className={styles.markdownTaskList}>
        {block.items.map((item, itemIndex) => (
          <li key={itemIndex}>
            <input type="checkbox" checked={item.checked} readOnly />
            <span>{renderInlineMarkdown(item.text, source, `${keyPrefix}-task-${itemIndex}`)}</span>
          </li>
        ))}
      </ul>
    )
  }
  if (block.type === 'code') {
    return (
      <pre>
        <code>{block.text}</code>
      </pre>
    )
  }
  return <hr />
}

function MarkdownText({ text, source, className }: { text: string; source?: NoteObject['source'] | null; className?: string }) {
  const blocks = parseMarkdownBlocks(text)
  return (
    <div className={`${styles.markdownText}${className ? ` ${className}` : ''}`}>
      {blocks.map((block, index) => <MarkdownBlockView key={index} block={block} source={source} index={index} />)}
    </div>
  )
}

const LINK_SNAPSHOT_TYPES: Array<{ jobType: 'markdown' | 'pdf'; label: string }> = [
  { jobType: 'markdown', label: 'MD' },
  { jobType: 'pdf', label: 'PDF' },
]

const TEXT_EXTRACTION_TYPES: Array<{ jobType: 'markdown'; label: string }> = [
  { jobType: 'markdown', label: 'Текст' },
]

function linkSnapshotJobBadge(
  kind: 'markdown' | 'pdf',
  views: SnapshotView[],
  jobs: SnapshotJob[],
): ReactNode {
  const view = views.find(v => v.kind === kind)
  const job = jobs.find(j => j.job_type === kind)
  if (view && (!job || job.status === 'done' || job.status === 'completed')) return null
  if (!view && !job) return null
  if (job?.status === 'failed') {
    return <span className={styles.assetTabJobFailed} title="Ошибка">!</span>
  }
  if (job) {
    const pct = job.status === 'processing' ? '50%' : '0%'
    return <span className={styles.assetTabJobPct} title="Готовится">{pct}</span>
  }
  return null
}

function snapshotArtifactView(artifact: SnapshotArtifact): SnapshotView | null {
  if (artifact.status !== 'ready') return null
  if (artifact.artifact_type === 'markdown') {
    return { kind: 'markdown', label: 'Текст', url: artifact.url }
  }
  if (artifact.artifact_type === 'pdf') {
    return { kind: 'pdf', label: 'PDF', url: artifact.url }
  }
  if (artifact.artifact_type === 'webpage_html') {
    return { kind: 'webpage_html', label: 'Website', url: artifact.url }
  }
  return null
}

function mergeSnapshotViews(primary: SnapshotView[], discovered: SnapshotView[]): SnapshotView[] {
  const byKind = new Map<SnapshotView['kind'], SnapshotView>()
  for (const view of primary) byKind.set(view.kind, view)
  for (const view of discovered) byKind.set(view.kind, view)
  return Array.from(byKind.values())
}

function EnrichmentPanel({ note }: { note: Note }) {
  const queryClient = useQueryClient()
  const [tagName, setTagName] = useState('')
  const [categoryQuery, setCategoryQuery] = useState('')
  const [categorySearch, setCategorySearch] = useState('')

  const contentTags = useQuery({
    queryKey: ['content-tags', note.id],
    queryFn: () => fetchContentTags(note.id),
  })
  const tagSuggestions = useQuery({
    queryKey: ['content-tag-suggestions', note.id],
    queryFn: () => fetchContentTagSuggestions(note.id),
  })
  const tagJobs = useQuery({
    queryKey: ['content-tag-jobs', note.id],
    queryFn: () => fetchContentTagJobs(note.id),
    refetchInterval: (query) => {
      const jobs = query.state.data ?? []
      return jobs.some(isActiveJob) ? 4000 : false
    },
  })
  const taxonomyAssignments = useQuery({
    queryKey: ['taxonomy-assignments', note.id],
    queryFn: () => fetchTaxonomyAssignments(note.id),
  })
  const taxonomyJobs = useQuery({
    queryKey: ['taxonomy-classification-jobs', note.id],
    queryFn: () => fetchTaxonomyClassificationJobs(note.id),
    refetchInterval: (query) => {
      const jobs = query.state.data ?? []
      return jobs.some(isActiveJob) ? 4000 : false
    },
  })
  const categories = useQuery({
    queryKey: ['taxonomy-category-search', categorySearch],
    queryFn: () => searchTaxonomyCategories(categorySearch),
    enabled: categorySearch.trim().length > 0,
  })

  function refreshEnrichment() {
    queryClient.invalidateQueries({ queryKey: ['content-tags', note.id] })
    queryClient.invalidateQueries({ queryKey: ['content-tag-suggestions', note.id] })
    queryClient.invalidateQueries({ queryKey: ['content-tag-jobs', note.id] })
    queryClient.invalidateQueries({ queryKey: ['taxonomy-assignments', note.id] })
    queryClient.invalidateQueries({ queryKey: ['taxonomy-classification-jobs', note.id] })
    queryClient.invalidateQueries({ queryKey: ['snapshot-jobs', note.id] })
    queryClient.invalidateQueries({ queryKey: ['note', note.id] })
    queryClient.invalidateQueries({ queryKey: ['notes'] })
  }

  const addTag = useMutation({
    mutationFn: async (name: string) => {
      const tag = await createOrFindTag(name)
      return assignExistingTagToContent(note.id, tag.id)
    },
    onSuccess: () => {
      setTagName('')
      refreshEnrichment()
    },
  })

  const acceptSuggestion = useMutation({
    mutationFn: (assignmentId: string) => acceptTagSuggestion(note.id, assignmentId),
    onSettled: refreshEnrichment,
  })
  const rejectSuggestion = useMutation({
    mutationFn: (assignmentId: string) => rejectTagSuggestion(note.id, assignmentId),
    onSettled: refreshEnrichment,
  })

  const assignCategory = useMutation({
    mutationFn: (categoryId: string) => assignCategoryToContent(note.id, categoryId),
    onSuccess: () => {
      setCategoryQuery('')
      setCategorySearch('')
      refreshEnrichment()
    },
  })

  const createAndAssignCategory = useMutation({
    mutationFn: async (name: string) => {
      const category = await createTaxonomyCategory(name)
      return assignCategoryToContent(note.id, category.id)
    },
    onSuccess: () => {
      setCategoryQuery('')
      setCategorySearch('')
      refreshEnrichment()
    },
  })

  const acceptCategory = useMutation({
    mutationFn: (assignmentId: string) => acceptTaxonomyAssignment(note.id, assignmentId),
    onSettled: refreshEnrichment,
  })
  const rejectCategory = useMutation({
    mutationFn: (assignmentId: string) => rejectTaxonomyAssignment(note.id, assignmentId),
    onSettled: refreshEnrichment,
  })

  const acceptedTags = contentTags.data?.filter(item => item.status === 'accepted') ?? []
  const pendingTags = tagSuggestions.data ?? []
  const tagJobItems = tagJobs.data ?? []
  const assignments = taxonomyAssignments.data ?? []
  const taxonomyJobItems = taxonomyJobs.data ?? []
  const currentAssignment = assignments.find(item => item.is_current) ?? null
  const proposedAssignments = assignments.filter(item => item.status === 'proposed')
  const category = note.taxonomyCategory ?? (currentAssignment
    ? {
        id: currentAssignment.category_id,
        name: currentAssignment.category_name_snapshot,
        slug: currentAssignment.category_path_snapshot.split('/').pop() ?? currentAssignment.category_id,
        path: currentAssignment.category_path_snapshot,
      }
    : null)
  const error = addTag.error ?? assignCategory.error ?? createAndAssignCategory.error

  function submitTag() {
    const trimmed = tagName.trim()
    if (trimmed) addTag.mutate(trimmed)
  }

  function searchCategory() {
    const trimmed = categoryQuery.trim()
    if (trimmed) setCategorySearch(trimmed)
  }

  return (
    <section className={styles.enrichmentPanel}>
      <div className={styles.enrichmentColumn}>
        <div className={styles.enrichmentHeader}>
          <TagIcon size={14} />
          <span>Теги</span>
        </div>
        <div className={styles.chipRow}>
          {(acceptedTags.length ? acceptedTags.map(item => item.tag) : note.tags).map(tag => {
            const { bg, text } = getTagColor(tag.name)
            return (
              <span key={tag.id} className={styles.tag} style={{ background: bg, color: text }}>
                {tag.name}
              </span>
            )
          })}
          {acceptedTags.length === 0 && note.tags.length === 0 && <span className={styles.emptyText}>Нет тегов</span>}
        </div>
        {pendingTags.length > 0 && (
          <div className={styles.suggestionList}>
            {pendingTags.map(item => (
              <div key={item.id} className={styles.suggestionItem}>
                <span>{item.tag.name}</span>
                {item.confidence !== null && <b>{Math.round(item.confidence * 100)}%</b>}
                <button onClick={() => acceptSuggestion.mutate(item.id)} title="Принять"><Check size={13} /></button>
                <button onClick={() => rejectSuggestion.mutate(item.id)} title="Отклонить"><X size={13} /></button>
              </div>
            ))}
          </div>
        )}
        {tagJobItems.length > 0 && (
          <div className={styles.jobList}>
            {tagJobItems.slice(0, 3).map(job => (
              <div key={job.id} className={styles.jobItem}>
                <span>{job.job_type}</span>
                <b>{enrichmentJobStatusLabel(job)}</b>
              </div>
            ))}
          </div>
        )}
        <div className={styles.inlineForm}>
          <input
            value={tagName}
            onChange={e => setTagName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') submitTag() }}
            placeholder="Новый тег"
          />
          <button onClick={submitTag} disabled={addTag.isPending || !tagName.trim()} title="Добавить тег">
            <Plus size={14} />
          </button>
        </div>
      </div>

      <div className={styles.enrichmentColumn}>
        <div className={styles.enrichmentHeader}>
          <FolderTree size={14} />
          <span>Категория</span>
        </div>
        {category ? (
          <div className={styles.categoryPill}>
            <strong>{category.name}</strong>
            <span>{category.path}</span>
          </div>
        ) : <span className={styles.emptyText}>Нет категории</span>}
        {proposedAssignments.length > 0 && (
          <div className={styles.suggestionList}>
            {proposedAssignments.map(item => (
              <div key={item.id} className={styles.suggestionItem}>
                <span>{item.category_name_snapshot}</span>
                {item.confidence !== null && <b>{Math.round(item.confidence * 100)}%</b>}
                <button onClick={() => acceptCategory.mutate(item.id)} title="Принять"><Check size={13} /></button>
                <button onClick={() => rejectCategory.mutate(item.id)} title="Отклонить"><X size={13} /></button>
              </div>
            ))}
          </div>
        )}
        {taxonomyJobItems.length > 0 && (
          <div className={styles.jobList}>
            {taxonomyJobItems.slice(0, 3).map(job => (
              <div key={job.id} className={styles.jobItem}>
                <span>{job.job_type}</span>
                <b>{job.result_status ?? enrichmentJobStatusLabel(job)}</b>
              </div>
            ))}
          </div>
        )}
        <div className={styles.inlineForm}>
          <input
            value={categoryQuery}
            onChange={e => setCategoryQuery(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') searchCategory() }}
            placeholder="Поиск категории"
          />
          <button onClick={searchCategory} disabled={!categoryQuery.trim()} title="Найти категорию">
            <Search size={14} />
          </button>
        </div>
        {categories.data && (
          <div className={styles.categoryResults}>
            {categories.data.map(item => (
              <button key={item.id} onClick={() => assignCategory.mutate(item.id)}>
                <span>{item.name}</span>
                <small>{item.path}</small>
              </button>
            ))}
            {categories.data.length === 0 && (
              <button onClick={() => createAndAssignCategory.mutate(categorySearch)}>
                <span>Создать категорию</span>
                <small>{categorySearch}</small>
              </button>
            )}
          </div>
        )}
        {!categories.data && categoryQuery.trim() && (
          <button
            className={styles.createCategoryBtn}
            onClick={() => createAndAssignCategory.mutate(categoryQuery)}
            disabled={createAndAssignCategory.isPending}
          >
            <Plus size={13} />
            Создать и назначить
          </button>
        )}
      </div>

      {error instanceof Error && <div className={styles.enrichmentError}>{error.message}</div>}
    </section>
  )
}

// ─── Image ─────────────────────────────────────────────────────────────────────

function ImageObj({
  obj,
  noteId,
  isEditing,
  isOpen,
  onOpen,
  onDelete,
}: {
  obj: NoteObject
  noteId: string
  isEditing: boolean
  isOpen: boolean
  onOpen: () => void
  onDelete: () => void
}) {
  return (
    <div className={`${styles.objWrapper} ${styles.objImage} ${obj.caption ? styles.objImageWithCaption : ''}`}>
      <AuthImage
        src={obj.content}
        alt=""
        style={{ cursor: 'zoom-in' }}
        onClick={() => window.open(obj.content, '_blank')}
      />
      <ObjectSource source={obj.source} />
      {obj.caption && <MarkdownText className={styles.objImageCaption} text={obj.caption} source={obj.source} />}
      <div className={styles.extractionCompanion}>
        <AssetViewer
          obj={obj}
          noteId={noteId}
          isEditing={false}
          isOpen={isOpen}
          onOpen={onOpen}
          onDelete={onDelete}
        />
      </div>
      {isEditing && <button className={styles.objDeleteBtn} onClick={onDelete}><X size={12} /></button>}
    </div>
  )
}

// ─── Text ──────────────────────────────────────────────────────────────────────

function TextObj({
  obj, isEditing, editValue, onChangeEdit, onDelete,
}: {
  obj: NoteObject; isEditing: boolean; editValue: string
  onChangeEdit: (v: string) => void; onDelete: () => void
}) {
  if (isEditing) {
    return (
      <div className={styles.objWrapper}>
        <textarea
          className={styles.objTextarea}
          value={editValue}
          onChange={e => onChangeEdit(e.target.value)}
        />
        <button className={styles.objDeleteBtn} onClick={onDelete}><X size={12} /></button>
      </div>
    )
  }
  return (
    <div className={styles.objWrapper}>
      <ObjectSource source={obj.source} />
      <MarkdownText className={styles.objText} text={obj.content} source={obj.source} />
    </div>
  )
}

function assetViewIcon(kind: SnapshotView['kind']) {
  if (kind === 'webpage_html') return <Globe size={13} />
  if (kind === 'pdf') return <FileDown size={13} />
  if (kind === 'markdown') return <FileText size={13} />
  return <Download size={13} />
}

function isAssetMode(view: SnapshotView) {
  return view.kind === 'webpage_html' || view.kind === 'pdf' || view.kind === 'markdown'
}

function assetDownloadName(obj: NoteObject, view: SnapshotView) {
  const ext = view.kind === 'markdown' ? 'md' : view.kind === 'webpage_html' ? 'html' : 'pdf'
  return `${getBaseName(obj.filename) || obj.id}.${ext}`
}

function PdfSnapshotView({ src }: { src: string }) {
  const [blobUrl, setBlobUrl] = useState<string | null>(() => docBlobCache.get(src) ?? null)
  const [loading, setLoading] = useState(() => !docBlobCache.has(src))

  useEffect(() => {
    if (docBlobCache.has(src)) {
      setBlobUrl(docBlobCache.get(src)!)
      setLoading(false)
      return
    }
    let objectUrl: string | null = null
    let cancelled = false
    setLoading(true)
    setBlobUrl(null)
    apiFetch(src)
      .then(r => r.blob())
      .then(blob => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(blob)
        docBlobCache.set(src, objectUrl)
        setBlobUrl(objectUrl)
        setLoading(false)
      })
      .catch(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [src])

  if (loading || !blobUrl) {
    return (
      <div className={styles.assetPanelLoader}>
        <LoaderSpinner />
      </div>
    )
  }
  return <PDFViewer src={blobUrl} />
}

function MarkdownSnapshotView({ src }: { src: string }) {
  const [text, setText] = useState<string | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    setText(null)
    setError(false)
    apiFetch(src)
      .then(r => {
        if (!r.ok) throw new Error('markdown fetch failed')
        return r.text()
      })
      .then(value => { if (!cancelled) setText(value) })
      .catch(() => {
        if (!cancelled) setError(true)
      })
    return () => { cancelled = true }
  }, [src])

  if (error) return <div className={styles.assetEmpty}>Не удалось загрузить Markdown</div>
  if (text === null) {
    return (
      <div className={styles.assetPanelLoader}>
        <LoaderSpinner />
      </div>
    )
  }
  return <pre className={styles.assetMarkdown}>{text}</pre>
}

function LinkSnapshotPending({ obj, favicon, domain }: { obj: NoteObject; favicon: string | null; domain: string }) {
  return (
    <div className={styles.objLinkSnapshotPending}>
      {favicon && <img src={favicon} alt="" className={styles.objLinkSnapshotIcon} />}
      <div className={styles.objLinkSnapshotDomain}>{domain}</div>
      <div className={styles.objLinkSnapshotUrl}>{obj.content}</div>
      <div className={styles.objLinkSnapshotBadge}>снимок страницы готовится</div>
    </div>
  )
}

function AssetViewer({
  obj,
  noteId,
  isEditing,
  isOpen,
  onOpen,
  onDelete,
}: {
  obj: NoteObject
  noteId: string
  isEditing: boolean
  isOpen: boolean
  onOpen: () => void
  onDelete: () => void
}) {
  const queryClient = useQueryClient()
  const { noteId: pageNoteId } = useParams<{ noteId: string }>()
  const baseViews = (obj.snapshotViews ?? []).filter(isAssetMode)
  const canExtractText = obj.type !== 'text'
  const [activeKind, setActiveKind] = useState<SnapshotView['kind'] | null>(() => baseViews[0]?.kind ?? null)
  const favicon = useFavicon(obj.type === 'link' ? obj.content : null)
  let domain = obj.content
  if (obj.type === 'link') {
    try {
      domain = new URL(obj.content).hostname.replace(/^www\./, '')
    } catch { /* ignore */ }
  }

  const { data: snapshotJobsNote } = useQuery({
    queryKey: ['snapshot-jobs', noteId],
    queryFn: () => fetchSnapshotJobs(noteId),
    enabled: canExtractText,
    refetchInterval: (query) => {
      const jobs = query.state.data ?? []
      return jobs.some(isActiveJob) ? 3000 : false
    },
  })
  const snapshotJobs = (snapshotJobsNote ?? []).filter(j => j.source_asset_id === obj.id)
  const { data: snapshotArtifactsNote } = useQuery({
    queryKey: ['snapshot-artifacts', noteId],
    queryFn: () => fetchSnapshotArtifacts(noteId),
    enabled: canExtractText,
    refetchInterval: () => snapshotJobs.some(isActiveJob) ? 3000 : false,
  })
  const discoveredViews = (snapshotArtifactsNote ?? [])
    .filter(artifact => artifact.source_asset_id === obj.id)
    .map(snapshotArtifactView)
    .filter((view): view is SnapshotView => view !== null)
    .filter(isAssetMode)
  const views = mergeSnapshotViews(baseViews, discoveredViews)
  const viewKey = views.map(view => `${view.kind}:${view.url}`).join('|')
  const markdownJob = snapshotJobs.find(j => j.job_type === 'markdown')
  const reprocessMarkdown = useMutation({
    mutationFn: () => reprocessSnapshotMarkdown(noteId, obj.id),
    onSuccess: () => {
      setActiveKind('markdown')
      queryClient.invalidateQueries({ queryKey: ['snapshot-jobs', noteId] })
      queryClient.invalidateQueries({ queryKey: ['snapshot-artifacts', noteId] })
      if (pageNoteId) queryClient.invalidateQueries({ queryKey: ['note', pageNoteId] })
      queryClient.invalidateQueries({ queryKey: ['notes'] })
      onOpen()
    },
  })

  useEffect(() => {
    const finishedJob = snapshotJobs.find(job => (job.status === 'done' || job.status === 'completed'))
    if (!finishedJob) return
    if ((obj.snapshotViews ?? []).some(v => v.kind === finishedJob.job_type)) return
    if (pageNoteId) queryClient.invalidateQueries({ queryKey: ['note', pageNoteId] })
    queryClient.invalidateQueries({ queryKey: ['snapshot-artifacts', noteId] })
    queryClient.invalidateQueries({ queryKey: ['notes'] })
  }, [noteId, obj.snapshotViews, pageNoteId, queryClient, snapshotJobs])

  const hasPendingOnlySlots =
    canExtractText &&
    (obj.type === 'link' ? LINK_SNAPSHOT_TYPES : TEXT_EXTRACTION_TYPES).some(({ jobType }) => {
      if (views.some(v => v.kind === jobType)) return false
      const job = snapshotJobs.find(j => j.job_type === jobType)
      return !!(job && job.status !== 'done' && job.status !== 'completed')
    })

  const showTabStrip = views.length > 1 || hasPendingOnlySlots

  useEffect(() => {
    if (views.length === 0) {
      setActiveKind(null)
      return
    }
    if (!activeKind || !views.some(view => view.kind === activeKind)) {
      setActiveKind(views[0].kind)
    }
  }, [activeKind, viewKey]) // eslint-disable-line react-hooks/exhaustive-deps

  const activeView = views.find(view => view.kind === activeKind) ?? views[0] ?? null
  const title = obj.type === 'link'
    ? domain
    : obj.type === 'image' || obj.type === 'audio' || obj.type === 'video'
      ? `Оцифровка · ${obj.filename ?? getBaseName(obj.filename)}`
      : getBaseName(obj.filename)

  return (
    <div className={styles.objWrapper}>
      <div className={`${styles.assetFrame} ${!isOpen ? styles.assetFrameCollapsed : ''}`}>
        <div className={styles.assetChrome} onClick={onOpen}>
          {obj.type === 'link' && favicon && <img src={favicon} alt="" className={styles.objLinkFavicon} />}
          <span className={styles.assetTitle}>{title}</span>
          {showTabStrip && (
            <div className={styles.assetTabs}>
              {views.map(view => (
                <button
                  key={`${obj.id}-${view.kind}`}
                  type="button"
                  className={`${styles.assetTab} ${activeView?.kind === view.kind ? styles.assetTabActive : ''}`}
                  onClick={event => {
                    event.stopPropagation()
                    setActiveKind(view.kind)
                    onOpen()
                  }}
                >
                  {assetViewIcon(view.kind)}
                  {view.label}
                  {obj.type === 'link' && (view.kind === 'pdf' || view.kind === 'markdown')
                    ? linkSnapshotJobBadge(view.kind, views, snapshotJobs)
                    : null}
                </button>
              ))}
              {obj.type === 'link' &&
                LINK_SNAPSHOT_TYPES.map(({ jobType, label }) => {
                  if (views.some(v => v.kind === jobType)) return null
                  const job = snapshotJobs.find(j => j.job_type === jobType)
                  if (!job || job.status === 'done' || job.status === 'completed') return null
                  const failed = job.status === 'failed'
                  const pct = job.status === 'processing' ? '50%' : '0%'
                  return (
                    <span
                      key={`${obj.id}-job-${jobType}`}
                      className={styles.assetTabPending}
                      aria-label={failed ? `${label}: ошибка` : `${label}: готовится`}
                    >
                      {SNAPSHOT_ICON[jobType] ?? <Download size={12} />}
                      {label}
                      <span className={failed ? styles.assetTabJobFailed : styles.assetTabJobPct}>
                        {failed ? '!' : pct}
                      </span>
                    </span>
                  )
                })}
              {obj.type !== 'link' &&
                TEXT_EXTRACTION_TYPES.map(({ jobType, label }) => {
                  if (views.some(v => v.kind === jobType)) return null
                  const job = snapshotJobs.find(j => j.job_type === jobType)
                  if (!job || job.status === 'done' || job.status === 'completed') return null
                  const failed = job.status === 'failed'
                  const pct = job.status === 'processing' ? '50%' : '0%'
                  return (
                    <span
                      key={`${obj.id}-job-${jobType}`}
                      className={styles.assetTabPending}
                      aria-label={failed ? `${label}: ошибка` : `${label}: готовится`}
                    >
                      {SNAPSHOT_ICON[jobType] ?? <Download size={12} />}
                      {label}
                      <span className={failed ? styles.assetTabJobFailed : styles.assetTabJobPct}>
                        {failed ? '!' : pct}
                      </span>
                    </span>
                  )
                })}
            </div>
          )}
          {canExtractText && (
            <button
              type="button"
              className={styles.assetAction}
              disabled={reprocessMarkdown.isPending || markdownJob?.status === 'processing'}
              onClick={event => {
                event.stopPropagation()
                reprocessMarkdown.mutate()
              }}
              title="Переоцифровать текст"
            >
              <RefreshCw size={13} />
            </button>
          )}
          {activeView && (
            <button
              type="button"
              className={styles.assetAction}
              onClick={event => {
                event.stopPropagation()
                authDownload(activeView.url, assetDownloadName(obj, activeView))
              }}
              title="Скачать текущий режим"
            >
              <Download size={13} />
            </button>
          )}
          {obj.type === 'link' && (
            <a
              className={styles.assetAction}
              href={obj.content}
              target="_blank"
              rel="noopener noreferrer"
              title="Открыть оригинал"
              onClick={event => event.stopPropagation()}
            >
              <ExternalLink size={13} />
            </a>
          )}
        </div>
        {(() => {
          const failedJob = snapshotJobs.find(j => j.status === 'failed' && j.error_message)
          if (!failedJob) return null
          return (
            <div className={styles.assetErrorNotice} role="status">
              <AlertTriangle size={12} />
              <span>{failedJob.error_message}</span>
            </div>
          )
        })()}
        {isOpen && (
          <div className={styles.assetBody}>
            <div
              className={styles.assetBodyInner}
              key={activeView ? `${activeKind}:${activeView.url}` : 'asset-view'}
            >
              {activeView?.kind === 'webpage_html' ? (
                <HtmlSnapshotViewer src={activeView.url} className={styles.assetWebsiteFrame} />
              ) : activeView?.kind === 'pdf' ? (
                <PdfSnapshotView src={activeView.url} />
              ) : activeView?.kind === 'markdown' ? (
                <MarkdownSnapshotView src={activeView.url} />
              ) : obj.type === 'link' ? (
                <LinkSnapshotPending obj={obj} favicon={favicon} domain={domain} />
              ) : markdownJob?.status === 'failed' ? (
                <div className={styles.assetEmpty}>Оцифровка завершилась ошибкой: {markdownJob.error_message ?? 'нет деталей'}</div>
              ) : markdownJob && isActiveJob(markdownJob) ? (
                <div className={styles.assetEmpty}>Оцифровка готовится</div>
              ) : (
                <div className={styles.assetEmpty}>Оцифровка еще не запускалась. Нажмите кнопку обновления выше.</div>
              )}
            </div>
          </div>
        )}
      </div>
      {isEditing && <button type="button" className={styles.objDeleteBtn} onClick={onDelete}><X size={12} /></button>}
    </div>
  )
}

// ─── Link ──────────────────────────────────────────────────────────────────────

function LinkObj({
  obj,
  noteId,
  isEditing,
  isOpen,
  onOpen,
  onDelete,
}: {
  obj: NoteObject
  noteId: string
  isEditing: boolean
  isOpen: boolean
  onOpen: () => void
  onDelete: () => void
}) {
  return <AssetViewer obj={obj} noteId={noteId} isEditing={isEditing} isOpen={isOpen} onOpen={onOpen} onDelete={onDelete} />
}

function MediaObj({
  obj,
  noteId,
  isEditing,
  isOpen,
  onOpen,
  onDelete,
  showExtraction = true,
}: {
  obj: NoteObject
  noteId: string
  isEditing: boolean
  isOpen: boolean
  onOpen: () => void
  onDelete: () => void
  showExtraction?: boolean
}) {
  const [mediaReady, setMediaReady] = useState(false)
  const media = useAuthenticatedObjectUrl(obj.content)
  useEffect(() => {
    setMediaReady(false)
  }, [media.url, obj.type])

  return (
    <div className={styles.objWrapper}>
      <div className={styles.mediaBox}>
        <div className={styles.mediaPlayerWrap}>
          {(!mediaReady || media.loading) && (
            <div className="appLoaderOverlay" aria-hidden>
              <LoaderSpinner />
            </div>
          )}
          {media.error && <div className={styles.mediaError}>Не удалось загрузить медиа</div>}
          {media.url && obj.type === 'audio' ? (
            <audio
              controls
              src={media.url}
              onLoadedData={() => setMediaReady(true)}
              onError={() => setMediaReady(true)}
            />
          ) : media.url ? (
            <video
              controls
              src={media.url}
              onLoadedData={() => setMediaReady(true)}
              onError={() => setMediaReady(true)}
            />
          ) : null}
        </div>
        <div className={styles.mediaMeta}>
          <span>{obj.filename ?? (obj.type === 'audio' ? 'Аудио' : 'Видео')}</span>
          {obj.sizeBytes !== undefined && <small>{formatBytes(obj.sizeBytes)}</small>}
        </div>
      </div>
      {showExtraction && (
        <div className={styles.extractionCompanion}>
          <AssetViewer
            obj={obj}
            noteId={noteId}
            isEditing={false}
            isOpen={isOpen}
            onOpen={onOpen}
            onDelete={onDelete}
          />
        </div>
      )}
      {isEditing && <button className={styles.objDeleteBtn} onClick={onDelete}><X size={12} /></button>}
    </div>
  )
}

function ProtectedVideo({ obj }: { obj: NoteObject }) {
  const media = useAuthenticatedObjectUrl(obj.content)
  if (media.error) return <div className={styles.mediaError}>Не удалось загрузить видео</div>
  if (!media.url) {
    return (
      <div className="appLoaderOverlay" aria-hidden>
        <LoaderSpinner />
      </div>
    )
  }
  return <video controls src={media.url} />
}

function ProtectedAudio({ obj }: { obj: NoteObject }) {
  const media = useAuthenticatedObjectUrl(obj.content)
  if (media.error) return <div className={styles.mediaError}>Не удалось загрузить аудио</div>
  if (!media.url) {
    return (
      <div className="appLoaderOverlay" aria-hidden>
        <LoaderSpinner />
      </div>
    )
  }
  return <audio controls src={media.url} />
}

// ─── Telegram detail post ─────────────────────────────────────────────────────

function TelegramDetailMediaTile({ obj }: { obj: NoteObject }) {
  if (obj.type === 'image') {
    return (
      <button className={styles.telegramDetailMediaTile} onClick={() => window.open(obj.content, '_blank')} title="Открыть изображение">
        <AuthImage src={getObjectPreviewSource(obj)} alt="" />
      </button>
    )
  }
  if (obj.type === 'video') {
    return (
      <div className={styles.telegramDetailMediaTile}>
        <ProtectedVideo obj={obj} />
      </div>
    )
  }
  if (obj.type === 'audio') {
    return (
      <div className={`${styles.telegramDetailMediaTile} ${styles.telegramDetailAudioTile}`}>
        <div className={styles.telegramDetailAudioIcon}>
          <Mic2 size={26} />
        </div>
        <ProtectedAudio obj={obj} />
        <span>{obj.filename ?? 'Голосовое сообщение'}</span>
      </div>
    )
  }
  if (obj.type === 'document') {
    const thumb = obj.thumbnailUrl ?? obj.cover
    return (
      <button className={styles.telegramDetailMediaTile} onClick={() => authDownload(obj.content, obj.filename)} title="Скачать документ">
        {thumb ? <AuthImage src={thumb} alt="" /> : <FileText size={30} />}
        <span>{obj.filename ?? 'Документ'}</span>
      </button>
    )
  }
  return null
}

function TelegramDetailPost({
  note,
  objects,
  model,
}: {
  note: Note
  objects: NoteObject[]
  model: TelegramCardModel
}) {
  const source = notePrimarySource(note, objects)
  const dateLabel = sourceDateLabel(source)
  const captionObj = objects.find(obj => obj.caption?.trim())
  const textObj = objects.find(obj => obj.type === 'text' && obj.content.trim())
  const caption = captionObj?.caption ?? textObj?.content ?? null
  const sourceTitle = model.originLabel ?? model.sourceLabel
  const media = model.media.filter(obj => objects.some(visible => visible.id === obj.id))
  const gridClass = [
    styles.telegramDetailMediaGrid,
    media.length === 1 ? styles.telegramDetailMediaSingle : '',
    media.length === 2 ? styles.telegramDetailMediaPair : '',
  ].filter(Boolean).join(' ')

  return (
    <article className={styles.telegramDetailPost}>
      <header className={styles.telegramDetailHeader}>
        <div className={styles.telegramDetailIcon}>
          <Send size={16} />
        </div>
        <div className={styles.telegramDetailSource}>
          <span>{model.sourceLabel}</span>
          <strong>{sourceTitle}</strong>
        </div>
        <div className={styles.telegramDetailMeta}>
          {dateLabel && <span>{dateLabel}</span>}
          {source?.url && (
            <a href={source.url} target="_blank" rel="noreferrer" title="Открыть оригинал">
              <ExternalLink size={14} />
            </a>
          )}
        </div>
      </header>

      {media.length > 0 && (
        <div className={gridClass}>
          {media.map(obj => <TelegramDetailMediaTile key={obj.id} obj={obj} />)}
        </div>
      )}

      {caption && (
        <MarkdownText className={styles.telegramDetailCaption} text={caption} source={captionObj?.source ?? textObj?.source ?? source} />
      )}
    </article>
  )
}

// ─── Document viewer ───────────────────────────────────────────────────────────

function DocViewer({
  obj,
  noteId,
  isEditing,
  isOpen,
  onOpen,
  onDelete,
}: {
  obj: NoteObject
  noteId: string
  isEditing: boolean
  isOpen: boolean
  onOpen: () => void
  onDelete: () => void
}) {
  return <AssetViewer obj={obj} noteId={noteId} isEditing={isEditing} isOpen={isOpen} onOpen={onOpen} onDelete={onDelete} />
}

// ─── Collection stream ─────────────────────────────────────────────────────────

function CollectionStream({
  objects,
  isEditing,
  openViewerId,
  onOpenViewer,
  onRemove,
}: {
  objects: NoteObject[]
  isEditing: boolean
  openViewerId: string | null
  onOpenViewer: (id: string) => void
  onRemove: (id: string, slug?: string) => void
}) {
  return (
    <div className={styles.stream}>
      {objects.map(obj => {
        const canOpen = Boolean(obj.id) && !isEditing
        const ariaLabel = `Открыть заметку: ${obj.filename ?? 'без названия'}`
        const wrap = (node: React.ReactNode) =>
          canOpen ? (
            <Link
              key={obj.id}
              to={`/notes/${obj.id}`}
              className={styles.objWrapperLink}
              aria-label={ariaLabel}
            >
              {node}
            </Link>
          ) : (
            node
          )
        const removeBtn = isEditing
          ? (
            <button
              className={styles.objDeleteBtn}
              onClick={e => { e.preventDefault(); e.stopPropagation(); onRemove(obj.id, obj.slug) }}
            >
              <X size={12} />
            </button>
          )
          : null

        if (obj.type === 'image') return wrap(
          <section
            key={canOpen ? undefined : obj.id}
            id={objectDomId(obj.id)}
            className={`${styles.objectSection} ${styles.objWrapper} ${styles.objImage} ${obj.caption ? styles.objImageWithCaption : ''}`}
          >
            <AuthImage
              src={obj.content}
              alt=""
              style={{ cursor: canOpen ? 'pointer' : 'zoom-in' }}
              onClick={canOpen ? undefined : () => window.open(obj.content, '_blank')}
            />
            <ObjectSource source={obj.source} />
            {obj.caption && <MarkdownText className={styles.objImageCaption} text={obj.caption} source={obj.source} />}
            {removeBtn}
          </section>
        )

        if (obj.type === 'document') return wrap(
          <section key={canOpen ? undefined : obj.id} id={objectDomId(obj.id)} className={`${styles.objectSection} ${styles.objWrapper}`}>
            <DocViewer
              obj={obj}
              noteId={obj.id}
              isEditing={isEditing}
              isOpen={openViewerId === obj.id}
              onOpen={() => onOpenViewer(obj.id)}
              onDelete={() => onRemove(obj.id, obj.slug)}
            />
          </section>
        )

        if (obj.type === 'link') return wrap(
          <section key={canOpen ? undefined : obj.id} id={objectDomId(obj.id)} className={`${styles.objectSection} ${styles.objWrapper}`}>
            <LinkObj
              obj={obj}
              noteId={obj.id}
              isEditing={isEditing}
              isOpen={openViewerId === obj.id}
              onOpen={() => onOpenViewer(obj.id)}
              onDelete={() => onRemove(obj.id, obj.slug)}
            />
          </section>
        )

        if (obj.type === 'text') return wrap(
          <section key={canOpen ? undefined : obj.id} id={objectDomId(obj.id)} className={`${styles.objectSection} ${styles.objWrapper}`}>
            <ObjectSource source={obj.source} />
            <MarkdownText className={styles.objText} text={obj.content} source={obj.source} />
            {removeBtn}
          </section>
        )

        if (obj.type === 'audio' || obj.type === 'video') return wrap(
          <section key={canOpen ? undefined : obj.id} id={objectDomId(obj.id)} className={`${styles.objectSection} ${styles.objWrapper}`}>
            <MediaObj
              obj={obj}
              noteId={obj.id}
              isEditing={isEditing}
              isOpen={openViewerId === obj.id}
              onOpen={() => onOpenViewer(obj.id)}
              onDelete={() => onRemove(obj.id, obj.slug)}
              showExtraction={false}
            />
          </section>
        )

        return null
      })}
    </div>
  )
}

// ─── Page ──────────────────────────────────────────────────────────────────────

export default function NotePage() {
  const { noteId: routeNoteId } = useParams<{ noteId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { data: note, isLoading } = useNote(routeNoteId!)
  const { mutate: updateNote } = useUpdateNote()
  const { mutate: removeItems } = useRemoveCollectionItems()

  // Prefetch doc blobs so preview is ready when DocViewer mounts
  useEffect(() => {
    note?.objects.filter(o => o.type === 'document').forEach(o => {
      const pdfUrl = o.snapshotViews?.find(v => v.kind === 'pdf')?.url
      if (pdfUrl) prefetchDocBlob(pdfUrl)
    })
  }, [note])

  const [isEditing,      setIsEditing]      = useState(false)
  const [editTitle,      setEditTitle]      = useState('')
  const [editTexts,      setEditTexts]      = useState<Record<string, string>>({})
  const [deletedObjs,    setDeletedObjs]    = useState<Set<string>>(new Set())
  const [removedSlugs,   setRemovedSlugs]   = useState<Set<string>>(new Set())
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const [openViewerId,   setOpenViewerId]   = useState<string | null>(null)

  const deleteNote = useMutation({
    mutationFn: () => deleteNotes(note ? [note.slug] : []),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['notes'] })
      await queryClient.invalidateQueries({ queryKey: ['notes-trash'] })
      navigate('/notes')
    },
  })

  useEffect(() => {
    const firstViewer = note?.objects.find(obj =>
      !deletedObjs.has(obj.id) && (obj.type === 'link' || obj.type === 'document')
    )
    if (!firstViewer) {
      if (openViewerId !== null) setOpenViewerId(null)
      return
    }
    const stillVisible = note?.objects.some(obj =>
      obj.id === openViewerId &&
      !deletedObjs.has(obj.id) &&
      (obj.type === 'link' || obj.type === 'document')
    )
    if (!stillVisible) setOpenViewerId(firstViewer.id)
  }, [deletedObjs, note, openViewerId])

  function enterEdit() {
    if (!note) return
    setEditTitle(note.title)
    const texts: Record<string, string> = {}
    note.objects.filter(o => o.type === 'text').forEach(o => { texts[o.id] = o.content })
    setDeletedObjs(new Set())
    setRemovedSlugs(new Set())
    setEditTexts(texts)
    setIsEditing(true)
  }

  function cancelEdit() { setIsEditing(false) }

  function saveEdit() {
    if (!note) return
    if (note.type === 'collection') {
      if (removedSlugs.size > 0) {
        removeItems({ collectionSlug: note.slug, itemSlugs: [...removedSlugs] })
      }
      updateNote({ noteRef: note.id, data: { title: editTitle || note.title } })
    } else {
      const objects = note.objects
        .filter(o => !deletedObjs.has(o.id))
        .map(o => o.type === 'text' ? { ...o, content: editTexts[o.id] ?? o.content } : o)
      updateNote({ noteRef: note.id, data: { title: editTitle || note.title, objects } })
    }
    setIsEditing(false)
  }

  if (isLoading) return null

  if (!note) {
    return (
      <div className={styles.page}>
        <div className={styles.notFound}>Заметка не найдена</div>
      </div>
    )
  }

  const visibleObjects = note.objects.filter(o => !deletedObjs.has(o.id))
  const telegramDetailModel = !isEditing
    ? getTelegramCardModel({ ...note, objects: visibleObjects })
    : null
  const formattedDate = formatDetailDate(note.createdAt)

  return (
    <div className={styles.page}>

      {/* Top bar */}
      <div className={styles.topBar}>
        <button className={styles.backBtn} onClick={() => navigate(-1)}>
          <ArrowLeft size={14} /> Заметки
        </button>
        <div className={styles.topBarActions}>
          {isEditing ? (
            <>
              <button className={styles.editBtn} onClick={cancelEdit}>Отмена</button>
              <button className={styles.saveBtn} onClick={saveEdit}>Сохранить</button>
            </>
          ) : (
            <>
              <button className={styles.editBtn} onClick={enterEdit}>Редактировать</button>
              <button className={styles.deleteNoteBtn} onClick={() => setDeleteConfirmOpen(value => !value)}>
                <Trash2 size={14} />
                Удалить
              </button>
            </>
          )}
        </div>
      </div>

      {deleteConfirmOpen && (
        <div className={styles.deleteConfirm}>
          <div>
            <strong>Удалить заметку?</strong>
            <span>Заметка попадёт в корзину, если она включена в настройках.</span>
          </div>
          <button className={styles.editBtn} onClick={() => setDeleteConfirmOpen(false)}>Отмена</button>
          <button
            className={styles.deleteNoteBtn}
            disabled={deleteNote.isPending}
            onClick={() => deleteNote.mutate()}
          >
            <Trash2 size={14} />
            {deleteNote.isPending ? 'Удаляю...' : 'Удалить'}
          </button>
          {deleteNote.isError && <span className={styles.deleteError}>Не удалось удалить заметку.</span>}
        </div>
      )}

      {/* Content */}
      <div className={styles.content}>
        <div className={styles.detailLayout}>
          <main className={styles.detailMain}>
            <div className={styles.meta}>
              <div className={styles.metaKicker}>
                <span>{noteTypeLabel(note)}</span>
                <span>{formattedDate}</span>
              </div>
              {isEditing
                ? <input
                    autoFocus
                    className={styles.titleInput}
                    value={editTitle}
                    onChange={e => setEditTitle(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') saveEdit() }}
                  />
                : <h1 className={styles.title}>{note.title}</h1>
              }
              <div className={styles.metaRow}>
                <TagList tags={note.tags} />
                {note.taxonomyCategory && (
                  <span className={styles.countBadge}>{note.taxonomyCategory.path}</span>
                )}
                {note.type === 'collection' && (
                  <span className={styles.countBadge}>{visibleObjects.length} элементов</span>
                )}
              </div>
            </div>

            {telegramDetailModel && (
              <TelegramDetailPost note={note} objects={visibleObjects} model={telegramDetailModel} />
            )}

            {!telegramDetailModel && note.type === 'collection' && (
              <CollectionStream
                objects={visibleObjects}
                isEditing={isEditing}
                openViewerId={openViewerId}
                onOpenViewer={setOpenViewerId}
                onRemove={(id, slug) => {
                  setDeletedObjs(p => new Set([...p, id]))
                  if (slug) setRemovedSlugs(p => new Set([...p, slug]))
                }}
              />
            )}

            {!telegramDetailModel && note.type !== 'collection' && (
              <div className={styles.stream}>
                {visibleObjects.map(obj => {
                  if (obj.type === 'image') return (
                    <section key={obj.id} id={objectDomId(obj.id)} className={styles.objectSection}>
                      <ImageObj
                        obj={obj} noteId={note.id} isEditing={isEditing}
                        isOpen={openViewerId === obj.id}
                        onOpen={() => setOpenViewerId(obj.id)}
                        onDelete={() => setDeletedObjs(p => new Set([...p, obj.id]))}
                      />
                    </section>
                  )
                  if (obj.type === 'link') return (
                    <section key={obj.id} id={objectDomId(obj.id)} className={styles.objectSection}>
                      <LinkObj
                        obj={obj} noteId={note.id} isEditing={isEditing}
                        isOpen={openViewerId === obj.id}
                        onOpen={() => setOpenViewerId(obj.id)}
                        onDelete={() => setDeletedObjs(p => new Set([...p, obj.id]))}
                      />
                    </section>
                  )
                  if (obj.type === 'document') return (
                    <section key={obj.id} id={objectDomId(obj.id)} className={styles.objectSection}>
                      <DocViewer
                        obj={obj}
                        noteId={note.id}
                        isEditing={isEditing}
                        isOpen={openViewerId === obj.id}
                        onOpen={() => setOpenViewerId(obj.id)}
                        onDelete={() => setDeletedObjs(p => new Set([...p, obj.id]))}
                      />
                    </section>
                  )
                  if (obj.type === 'text') return (
                    <section key={obj.id} id={objectDomId(obj.id)} className={styles.objectSection}>
                      <TextObj
                        obj={obj} isEditing={isEditing}
                        editValue={editTexts[obj.id] ?? obj.content}
                        onChangeEdit={v => setEditTexts(p => ({ ...p, [obj.id]: v }))}
                        onDelete={() => setDeletedObjs(p => new Set([...p, obj.id]))}
                      />
                    </section>
                  )
                  if (obj.type === 'audio' || obj.type === 'video') return (
                    <section key={obj.id} id={objectDomId(obj.id)} className={styles.objectSection}>
                      <MediaObj
                        obj={obj} noteId={note.id} isEditing={isEditing}
                        isOpen={openViewerId === obj.id}
                        onOpen={() => setOpenViewerId(obj.id)}
                        onDelete={() => setDeletedObjs(p => new Set([...p, obj.id]))}
                      />
                    </section>
                  )
                  return null
                })}
              </div>
            )}
          </main>

          <aside className={styles.detailSidebar}>
            <NoteOverview note={note} objects={visibleObjects} />
            <EnrichmentPanel note={note} />
          </aside>
        </div>
      </div>
    </div>
  )
}
