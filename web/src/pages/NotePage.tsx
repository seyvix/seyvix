import { useState, useEffect } from 'react'
import type { ReactNode } from 'react'
import PDFViewer from '../components/PDFViewer/PDFViewer'
import { useFavicon } from '../hooks/useFavicon'
import { useParams, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  ExternalLink,
  FileText,
  FileDown,
  Globe,
  Download,
  X,
  ChevronRight,
  Check,
  FolderTree,
  Plus,
  Search,
  Tag as TagIcon,
} from 'lucide-react'
import { useNote } from '../hooks/useNote'
import { useUpdateNote } from '../hooks/useUpdateNote'
import { useRemoveCollectionItems } from '../hooks/useRemoveCollectionItems'
import { getTagColor } from '../utils/tagColor'
import AuthImage from '../components/AuthImage/AuthImage'
import HtmlSnapshotViewer from '../components/HtmlSnapshotViewer/HtmlSnapshotViewer'
import { LoaderSpinner } from '../components/LoaderSpinner'
import { apiFetch } from '../lib/apiClient'
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
  fetchSnapshotJobs,
  fetchTaxonomyAssignments,
  fetchTaxonomyClassificationJobs,
  rejectTagSuggestion,
  rejectTaxonomyAssignment,
  searchTaxonomyCategories,
  type ContentTagAssignment,
  type ContentTagJob,
  type SnapshotJob,
  type TaxonomyAssignment,
  type TaxonomyClassificationJob,
} from '../api/enrichment'
import type { Note, NoteObject, SnapshotView, Tag } from '../types'
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

function MarkdownText({ text }: { text: string }) {
  const pattern = /!\[favicon\]\(([^)]+)\)\s+\[([^\]]+)\]\(([^)]+)\)/g
  const parts: ReactNode[] = []
  let lastIndex = 0

  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0
    if (index > lastIndex) {
      parts.push(text.slice(lastIndex, index))
    }
    const [, faviconUrl, label, href] = match
    parts.push(
      <a
        key={`${href}-${index}`}
        className={styles.inlineMarkdownLink}
        href={href}
        target="_blank"
        rel="noopener noreferrer"
      >
        <img src={faviconUrl} alt="" />
        <span>{label}</span>
      </a>
    )
    lastIndex = index + match[0].length
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }

  return <>{parts}</>
}

const LINK_SNAPSHOT_TYPES: Array<{ jobType: 'markdown' | 'pdf'; label: string }> = [
  { jobType: 'markdown', label: 'MD' },
  { jobType: 'pdf', label: 'PDF' },
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

function ImageObj({ obj, isEditing, onDelete }: { obj: NoteObject; isEditing: boolean; onDelete: () => void }) {
  return (
    <div className={`${styles.objWrapper} ${styles.objImage}`}>
      <AuthImage
        src={obj.content}
        alt=""
        style={{ cursor: 'zoom-in' }}
        onClick={() => window.open(obj.content, '_blank')}
      />
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
    <>
      <p className={styles.objText}><MarkdownText text={obj.content} /></p>
    </>
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
  const views = (obj.snapshotViews ?? []).filter(isAssetMode)
  const viewKey = views.map(view => `${view.kind}:${view.url}`).join('|')
  const [activeKind, setActiveKind] = useState<SnapshotView['kind'] | null>(() => views[0]?.kind ?? null)
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
    enabled: obj.type === 'link',
    refetchInterval: (query) => {
      if (obj.type !== 'link') return false
      const jobs = query.state.data ?? []
      return jobs.some(isActiveJob) ? 3000 : false
    },
  })
  const snapshotJobs = (snapshotJobsNote ?? []).filter(j => j.source_asset_id === obj.id)
  const webpageHtmlJob = snapshotJobs.find(j => j.job_type === 'webpage_html')

  useEffect(() => {
    if (obj.type !== 'link') return
    if (webpageHtmlJob?.status !== 'done') return
    if ((obj.snapshotViews ?? []).some(v => v.kind === 'webpage_html')) return
    if (pageNoteId) queryClient.invalidateQueries({ queryKey: ['note', pageNoteId] })
    queryClient.invalidateQueries({ queryKey: ['notes'] })
  }, [obj.type, obj.snapshotViews, pageNoteId, queryClient, webpageHtmlJob?.status])

  const hasPendingOnlySlots =
    obj.type === 'link' &&
    LINK_SNAPSHOT_TYPES.some(({ jobType }) => {
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
  const title = obj.type === 'link' ? domain : getBaseName(obj.filename)

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
            </div>
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
              ) : (
                <div className={styles.assetEmpty}>Нет доступных режимов просмотра</div>
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

function MediaObj({ obj, isEditing, onDelete }: { obj: NoteObject; isEditing: boolean; onDelete: () => void }) {
  const [mediaReady, setMediaReady] = useState(false)
  useEffect(() => {
    setMediaReady(false)
  }, [obj.content, obj.type])

  return (
    <div className={styles.objWrapper}>
      <div className={styles.mediaBox}>
        <div className={styles.mediaPlayerWrap}>
          {!mediaReady && (
            <div className="appLoaderOverlay" aria-hidden>
              <LoaderSpinner />
            </div>
          )}
          {obj.type === 'audio' ? (
            <audio
              controls
              src={obj.content}
              onLoadedData={() => setMediaReady(true)}
              onError={() => setMediaReady(true)}
            />
          ) : (
            <video
              controls
              src={obj.content}
              onLoadedData={() => setMediaReady(true)}
              onError={() => setMediaReady(true)}
            />
          )}
        </div>
        <div className={styles.mediaMeta}>
          <span>{obj.filename ?? (obj.type === 'audio' ? 'Аудио' : 'Видео')}</span>
          {obj.sizeBytes !== undefined && <small>{formatBytes(obj.sizeBytes)}</small>}
        </div>
      </div>
      {isEditing && <button className={styles.objDeleteBtn} onClick={onDelete}><X size={12} /></button>}
    </div>
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
  const navigate = useNavigate()

  return (
    <div className={styles.stream}>
      {objects.map(obj => {
        const canNavigate = Boolean(obj.id)
        const hint = canNavigate && !isEditing
          ? (
            <button
              className={styles.collOpenBtn}
              onClick={() => navigate(`/notes/${obj.id}`)}
              title="Открыть заметку"
            >
              <ChevronRight size={13} />
            </button>
          )
          : null
        const removeBtn = isEditing
          ? (
            <button
              className={styles.objDeleteBtn}
              onClick={e => { e.stopPropagation(); onRemove(obj.id, obj.slug) }}
            >
              <X size={12} />
            </button>
          )
          : null

        if (obj.type === 'image') return (
          <div key={obj.id} className={`${styles.objWrapper} ${styles.objImage}`}>
            <AuthImage
              src={obj.content}
              alt=""
              style={{ cursor: canNavigate && !isEditing ? 'pointer' : 'zoom-in' }}
              onClick={() => !isEditing && canNavigate ? navigate(`/notes/${obj.id}`) : window.open(obj.content, '_blank')}
            />
            {hint}
            {removeBtn}
          </div>
        )

        if (obj.type === 'document') return (
          <div key={obj.id} className={styles.objWrapper}>
            <DocViewer
              obj={obj}
              noteId={obj.id}
              isEditing={isEditing}
              isOpen={openViewerId === obj.id}
              onOpen={() => onOpenViewer(obj.id)}
              onDelete={() => onRemove(obj.id, obj.slug)}
            />
            {hint}
          </div>
        )

        if (obj.type === 'link') return (
          <div key={obj.id} className={styles.objWrapper}>
            <LinkObj
              obj={obj}
              noteId={obj.id}
              isEditing={isEditing}
              isOpen={openViewerId === obj.id}
              onOpen={() => onOpenViewer(obj.id)}
              onDelete={() => onRemove(obj.id, obj.slug)}
            />
            {hint}
          </div>
        )

        if (obj.type === 'text') return (
          <div key={obj.id} className={styles.objWrapper}>
            <p className={styles.objText}><MarkdownText text={obj.content} /></p>
            {hint}
            {removeBtn}
          </div>
        )

        if (obj.type === 'audio' || obj.type === 'video') return (
          <div key={obj.id} className={styles.objWrapper}>
            <MediaObj obj={obj} isEditing={isEditing} onDelete={() => onRemove(obj.id, obj.slug)} />
            {hint}
          </div>
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
  const [openViewerId,   setOpenViewerId]   = useState<string | null>(null)

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
  const formattedDate  = new Date(note.updatedAt).toLocaleDateString('ru-RU', {
    day: 'numeric', month: 'long', year: 'numeric',
  })

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
            <button className={styles.editBtn} onClick={enterEdit}>Редактировать</button>
          )}
        </div>
      </div>

      {/* Content */}
      <div className={styles.content}>
        {/* Meta */}
        <div className={styles.meta}>
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
            <span className={styles.date}>{formattedDate}</span>
            {note.type === 'collection' && (
              <span className={styles.countBadge}>{visibleObjects.length} элементов</span>
            )}
          </div>
        </div>

        <EnrichmentPanel note={note} />

        {/* Collection → article stream */}
        {note.type === 'collection' && (
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

        {/* Simple / Composite → stream */}
        {note.type !== 'collection' && (
          <div className={styles.stream}>
            {visibleObjects.map(obj => {
              if (obj.type === 'image') return (
                <ImageObj
                  key={obj.id} obj={obj} isEditing={isEditing}
                  onDelete={() => setDeletedObjs(p => new Set([...p, obj.id]))}
                />
              )
              if (obj.type === 'link') return (
                <LinkObj
                  key={obj.id} obj={obj} noteId={note.id} isEditing={isEditing}
                  isOpen={openViewerId === obj.id}
                  onOpen={() => setOpenViewerId(obj.id)}
                  onDelete={() => setDeletedObjs(p => new Set([...p, obj.id]))}
                />
              )
              if (obj.type === 'document') return (
                <DocViewer
                  key={obj.id}
                  obj={obj}
                  noteId={note.id}
                  isEditing={isEditing}
                  isOpen={openViewerId === obj.id}
                  onOpen={() => setOpenViewerId(obj.id)}
                  onDelete={() => setDeletedObjs(p => new Set([...p, obj.id]))}
                />
              )
              if (obj.type === 'text') return (
                <TextObj
                  key={obj.id} obj={obj} isEditing={isEditing}
                  editValue={editTexts[obj.id] ?? obj.content}
                  onChangeEdit={v => setEditTexts(p => ({ ...p, [obj.id]: v }))}
                  onDelete={() => setDeletedObjs(p => new Set([...p, obj.id]))}
                />
              )
              if (obj.type === 'audio' || obj.type === 'video') return (
                <MediaObj
                  key={obj.id} obj={obj} isEditing={isEditing}
                  onDelete={() => setDeletedObjs(p => new Set([...p, obj.id]))}
                />
              )
              return null
            })}
          </div>
        )}

      </div>
    </div>
  )
}
