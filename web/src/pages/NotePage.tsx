import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  ExternalLink,
  FileText,
  Download,
  X,
  ChevronRight,
  Check,
  FolderTree,
  Maximize2,
  Plus,
  RefreshCw,
  Search,
  Tag as TagIcon,
} from 'lucide-react'
import { useNote } from '../hooks/useNote'
import { useUpdateNote } from '../hooks/useUpdateNote'
import { useRemoveCollectionItems } from '../hooks/useRemoveCollectionItems'
import { getTagColor } from '../utils/tagColor'
import AuthImage from '../components/AuthImage/AuthImage'
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
  fetchSnapshotArtifacts,
  fetchSnapshotJobs,
  fetchTaxonomyAssignments,
  fetchTaxonomyClassificationJobs,
  rejectTagSuggestion,
  rejectTaxonomyAssignment,
  searchTaxonomyCategories,
  type ContentTagAssignment,
  type ContentTagJob,
  type SnapshotArtifact,
  type SnapshotJob,
  type TaxonomyAssignment,
  type TaxonomyClassificationJob,
} from '../api/enrichment'
import type { Note, NoteObject, Tag } from '../types'
import type { SnapshotView } from '../types'
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

function artifactLabel(artifact: SnapshotArtifact): string {
  if (artifact.artifact_type === 'webpage_html') return 'HTML'
  if (artifact.artifact_type === 'thumbnail') return 'Миниатюра'
  if (artifact.artifact_type === 'markdown') return 'Markdown'
  if (artifact.artifact_type === 'pdf') return 'PDF'
  return artifact.artifact_type
}

function jobStatusLabel(job: SnapshotJob): string {
  if (job.status === 'completed' || job.status === 'done') return 'Готово'
  if (job.status === 'failed') return 'Ошибка'
  if (job.status === 'processing') return 'Обработка'
  return 'В очереди'
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

function SnapshotViewerModal({
  view,
  onClose,
}: {
  view: SnapshotView
  onClose: () => void
}) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [text, setText] = useState<string | null>(null)
  const [isFullscreen, setIsFullscreen] = useState(false)

  useEffect(() => {
    let objectUrl: string | null = null
    let cancelled = false
    setBlobUrl(null)
    setText(null)
    async function loadView() {
      try {
        const res = await apiFetch(view.url)
        if (!res.ok) throw new Error('fetch failed')
        if (view.kind === 'markdown') {
          const data = await res.text()
          if (cancelled) return
          setText(data)
          return
        }
        const data = await res.blob()
        if (cancelled) return
        objectUrl = URL.createObjectURL(data)
        setBlobUrl(objectUrl)
      } catch {
        if (!cancelled) setBlobUrl(view.url)
      }
    }
    void loadView()
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [view])

  return (
    <div className={`${styles.snapshotModal}${isFullscreen ? ` ${styles.snapshotModalFullscreen}` : ''}`}>
      <div className={styles.snapshotModalHeader}>
        <span>{view.label}</span>
        <a href={view.url} download>
          <Download size={14} /> Скачать
        </a>
        <button onClick={() => setIsFullscreen(value => !value)} title="Полный экран">
          <Maximize2 size={14} />
        </button>
        <button onClick={onClose} title="Закрыть">
          <X size={14} />
        </button>
      </div>
      <div className={styles.snapshotModalBody}>
        {view.kind === 'markdown' ? (
          <pre className={styles.markdownPreview}>{text ?? 'Загрузка...'}</pre>
        ) : view.kind === 'thumbnail' ? (
          blobUrl ? <AuthImage src={view.url} alt="" className={styles.snapshotImagePreview} /> : <span className={styles.emptyText}>Загрузка...</span>
        ) : (
          blobUrl ? <iframe src={blobUrl} title={view.label} className={styles.snapshotFrame} /> : <span className={styles.emptyText}>Загрузка...</span>
        )}
      </div>
    </div>
  )
}

function SnapshotLinks({ obj }: { obj: NoteObject }) {
  const [activeView, setActiveView] = useState<SnapshotView | null>(null)
  const views = obj.snapshotViews ?? []
  if (views.length === 0) return null
  return (
    <>
      <div className={styles.snapshotLinks}>
        {views.map(view => (
          <button key={`${obj.id}-${view.kind}`} onClick={() => setActiveView(view)}>
            {view.label}
          </button>
        ))}
      </div>
      {activeView && (
        <SnapshotViewerModal
          view={activeView}
          onClose={() => setActiveView(null)}
        />
      )}
    </>
  )
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
  const snapshotArtifacts = useQuery({
    queryKey: ['snapshot-artifacts', note.id],
    queryFn: () => fetchSnapshotArtifacts(note.id),
    refetchInterval: (query) => {
      const jobs = queryClient.getQueryData<SnapshotJob[]>(['snapshot-jobs', note.id]) ?? []
      return jobs.some(isActiveJob) ? 4000 : false
    },
  })
  const snapshotJobs = useQuery({
    queryKey: ['snapshot-jobs', note.id],
    queryFn: () => fetchSnapshotJobs(note.id),
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
    queryClient.invalidateQueries({ queryKey: ['snapshot-artifacts', note.id] })
    queryClient.invalidateQueries({ queryKey: ['snapshot-jobs', note.id] })
    queryClient.invalidateQueries({ queryKey: ['note', note.slug] })
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
  const artifacts = snapshotArtifacts.data ?? []
  const jobs = snapshotJobs.data ?? []
  const activeJobs = jobs.filter(isActiveJob)
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

      <div className={styles.enrichmentColumn}>
        <div className={styles.enrichmentHeader}>
          <FileText size={14} />
          <span>Снапшоты</span>
          <button className={styles.iconTextBtn} onClick={refreshEnrichment}>
            <RefreshCw size={13} />
            Обновить
          </button>
        </div>
        {artifacts.length > 0 ? (
          <div className={styles.artifactList}>
            {artifacts.map(artifact => (
              <a key={artifact.id} href={artifact.url} target="_blank" rel="noopener noreferrer">
                <span>{artifactLabel(artifact)}</span>
                <small>{formatBytes(artifact.size_bytes)}</small>
              </a>
            ))}
          </div>
        ) : (
          <span className={styles.emptyText}>
            {activeJobs.length > 0 ? 'Обработка' : 'Нет артефактов'}
          </span>
        )}
        {jobs.length > 0 && (
          <div className={styles.jobList}>
            {jobs.slice(0, 4).map(job => (
              <div key={job.id} className={styles.jobItem}>
                <span>{job.job_type}</span>
                <b>{jobStatusLabel(job)}</b>
              </div>
            ))}
          </div>
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
      <p className={styles.objText}>{obj.content}</p>
      <SnapshotLinks obj={obj} />
    </>
  )
}

// ─── Link ──────────────────────────────────────────────────────────────────────

function makeLinkSrcdoc(url: string, domain: string): string {
  const escaped = url.replace(/"/g, '&quot;')
  return `<!DOCTYPE html><html><head><meta charset="utf-8"><style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;background:#0f0f0f;color:#f5f5f5;height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;user-select:none}img{width:48px;height:48px;border-radius:10px}.domain{font-size:22px;font-weight:600;color:#e5e5e5}.url{font-size:12px;color:#555;max-width:320px;text-align:center;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.badge{font-size:10px;color:#444;border:1px solid #2a2a2a;border-radius:20px;padding:3px 10px;margin-top:8px}</style></head><body><img src="https://www.google.com/s2/favicons?domain=${domain}&sz=96" onerror="this.style.display='none'"/><div class="domain">${domain}</div><div class="url">${escaped}</div><div class="badge">снапшот</div></body></html>`
}

function LinkObj({ obj, isEditing, onDelete }: { obj: NoteObject; isEditing: boolean; onDelete: () => void }) {
  let domain = obj.content
  let favicon = ''
  try {
    const u = new URL(obj.content)
    domain  = u.hostname.replace(/^www\./, '')
    favicon = `https://www.google.com/s2/favicons?domain=${u.hostname}&sz=32`
  } catch { /* ignore */ }

  return (
    <div className={styles.objWrapper}>
      <div className={styles.objLinkFrame}>
        <div className={styles.objLinkChrome}>
          {favicon && <img src={favicon} alt="" className={styles.objLinkFavicon} />}
          <span className={styles.objLinkChromeDomain}>{domain}</span>
          <a className={styles.objLinkChromeOpen} href={obj.content} target="_blank" rel="noopener noreferrer">
            <ExternalLink size={13} />
          </a>
        </div>
        <iframe
          className={styles.objLinkIframe}
          srcDoc={makeLinkSrcdoc(obj.content, domain)}
          sandbox="allow-same-origin"
          title={domain}
        />
      </div>
      {isEditing && <button className={styles.objDeleteBtn} onClick={onDelete}><X size={12} /></button>}
    </div>
  )
}

function MediaObj({ obj, isEditing, onDelete }: { obj: NoteObject; isEditing: boolean; onDelete: () => void }) {
  return (
    <div className={styles.objWrapper}>
      <div className={styles.mediaBox}>
        {obj.type === 'audio' ? (
          <audio controls src={obj.content} />
        ) : (
          <video controls src={obj.content} />
        )}
        <div className={styles.mediaMeta}>
          <span>{obj.filename ?? (obj.type === 'audio' ? 'Аудио' : 'Видео')}</span>
          {obj.sizeBytes !== undefined && <small>{formatBytes(obj.sizeBytes)}</small>}
        </div>
        <SnapshotLinks obj={obj} />
      </div>
      {isEditing && <button className={styles.objDeleteBtn} onClick={onDelete}><X size={12} /></button>}
    </div>
  )
}

// ─── Document viewer ───────────────────────────────────────────────────────────

function DocViewer({ obj, isEditing, onDelete }: { obj: NoteObject; isEditing: boolean; onDelete: () => void }) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [tab,     setTab]     = useState<'view' | 'info'>('view')

  useEffect(() => {
    let objectUrl: string | null = null
    setLoading(true)
    setBlobUrl(null)
    apiFetch(obj.content)
      .then(r => r.blob())
      .then(blob => {
        objectUrl = URL.createObjectURL(blob)
        setBlobUrl(objectUrl)
        setLoading(false)
      })
      .catch(() => setLoading(false))
    return () => { if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [obj.content])

  const isPDF  = obj.filename?.toLowerCase().endsWith('.pdf') ?? false
  const ext    = getExt(obj.filename)
  const name   = getBaseName(obj.filename)
  const thumb  = obj.thumbnailUrl ?? obj.cover

  return (
    <div className={`${styles.objWrapper} ${styles.docViewer}`}>

      {/* Tab bar */}
      <div className={styles.docTabs}>
        <button
          className={`${styles.docTab}${tab === 'view' ? ` ${styles.docTabActive}` : ''}`}
          onClick={() => setTab('view')}
        >
          Просмотр
        </button>
        <button
          className={`${styles.docTab}${tab === 'info' ? ` ${styles.docTabActive}` : ''}`}
          onClick={() => setTab('info')}
        >
          Информация
        </button>
        <div className={styles.docTabSpacer} />
        <span className={styles.docTabFilename}>{name}</span>
        <span className={styles.docTabExt}>{ext}</span>
      </div>
      <SnapshotLinks obj={obj} />

      {/* View tab */}
      {tab === 'view' && (
        <div className={styles.docViewPane}>
          {loading ? (
            <div className={styles.docViewLoading}>
              <div className={styles.docViewShimmer} />
            </div>
          ) : blobUrl && isPDF ? (
            <iframe src={blobUrl} className={styles.docIframe} title={obj.filename} />
          ) : (
            <div className={styles.docViewFallback}>
              {thumb
                ? <AuthImage src={thumb} alt="" className={styles.docThumb} />
                : <div className={styles.docFallbackIcon}><FileText size={40} /></div>
              }
              <p className={styles.docFallbackMsg}>
                Предпросмотр недоступен для .{ext.toLowerCase()}
              </p>
              {blobUrl && (
                <a href={blobUrl} download={obj.filename} className={styles.docDownloadBtn}>
                  <Download size={14} /> Скачать файл
                </a>
              )}
            </div>
          )}
        </div>
      )}

      {/* Info tab */}
      {tab === 'info' && (
        <div className={styles.docInfoPane}>
          <div className={styles.docInfoPreview}>
            {thumb
              ? <AuthImage src={thumb} alt="" className={styles.docInfoThumb} />
              : <div className={styles.docInfoIconWrap}><FileText size={32} /></div>
            }
          </div>
          <div className={styles.docInfoRows}>
            <div className={styles.docInfoRow}>
              <span className={styles.docInfoLabel}>Имя файла</span>
              <span className={styles.docInfoValue}>{obj.filename ?? '—'}</span>
            </div>
            <div className={styles.docInfoRow}>
              <span className={styles.docInfoLabel}>Формат</span>
              <span className={`${styles.docInfoValue} ${styles.docInfoExt}`}>{ext}</span>
            </div>
          </div>
          {blobUrl && (
            <a href={blobUrl} download={obj.filename} className={styles.docDownloadBtn}>
              <Download size={14} /> Скачать файл
            </a>
          )}
        </div>
      )}

      {isEditing && <button className={styles.objDeleteBtn} onClick={onDelete}><X size={12} /></button>}
    </div>
  )
}

// ─── Collection stream ─────────────────────────────────────────────────────────

function CollectionStream({
  objects,
  isEditing,
  onRemove,
}: {
  objects: NoteObject[]
  isEditing: boolean
  onRemove: (id: string, slug?: string) => void
}) {
  const navigate = useNavigate()

  return (
    <div className={styles.stream}>
      {objects.map(obj => {
        const canNavigate = Boolean(obj.slug)
        const hint = canNavigate && !isEditing
          ? (
            <button
              className={styles.collOpenBtn}
              onClick={() => navigate(`/notes/${obj.slug}`)}
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
              onClick={() => !isEditing && canNavigate ? navigate(`/notes/${obj.slug}`) : window.open(obj.content, '_blank')}
            />
            {hint}
            {removeBtn}
          </div>
        )

        if (obj.type === 'document') return (
          <div key={obj.id} className={styles.objWrapper}>
            <DocViewer obj={obj} isEditing={isEditing} onDelete={() => onRemove(obj.id, obj.slug)} />
            {hint}
          </div>
        )

        if (obj.type === 'text') return (
          <div key={obj.id} className={styles.objWrapper}>
            <p className={styles.objText}>{obj.content}</p>
            <SnapshotLinks obj={obj} />
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
  const { noteSlug } = useParams<{ noteSlug: string }>()
  const navigate = useNavigate()
  const { data: note, isLoading } = useNote(noteSlug!)
  const { mutate: updateNote } = useUpdateNote()
  const { mutate: removeItems } = useRemoveCollectionItems()

  const [isEditing,      setIsEditing]      = useState(false)
  const [editTitle,      setEditTitle]      = useState('')
  const [editTexts,      setEditTexts]      = useState<Record<string, string>>({})
  const [deletedObjs,    setDeletedObjs]    = useState<Set<string>>(new Set())
  const [removedSlugs,   setRemovedSlugs]   = useState<Set<string>>(new Set())

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
      updateNote({ slug: note.slug, data: { title: editTitle || note.title } })
    } else {
      const objects = note.objects
        .filter(o => !deletedObjs.has(o.id))
        .map(o => o.type === 'text' ? { ...o, content: editTexts[o.id] ?? o.content } : o)
      updateNote({ slug: note.slug, data: { title: editTitle || note.title, objects } })
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
                  key={obj.id} obj={obj} isEditing={isEditing}
                  onDelete={() => setDeletedObjs(p => new Set([...p, obj.id]))}
                />
              )
              if (obj.type === 'document') return (
                <DocViewer
                  key={obj.id} obj={obj} isEditing={isEditing}
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
