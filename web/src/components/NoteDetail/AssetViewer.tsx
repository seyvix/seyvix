import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Download, ExternalLink, FileDown, FileText, Globe, Maximize2, RefreshCw, X } from 'lucide-react'
import { LoaderSpinner } from '../LoaderSpinner'
import { apiFetch } from '../../lib/apiClient'
import { reprocessSnapshotMarkdown, type SnapshotJob } from '../../api/enrichment'
import { useFavicon } from '../../hooks/useFavicon'
import { requestChangeFeedSync } from '../../hooks/useNotesChangeFeed'
import { useAiEnabled } from '../../hooks/useSearchCapabilities'
import type { NoteObject } from '../../types'
import { startDownload } from './download'
import { baseFileName, isActiveJob, isFinishedJob, linkDomain } from './format'
import { FullscreenDialog } from './FullscreenDialog'
import { useObjectSnapshots, type AssetView, type AssetViewKind } from './useObjectSnapshots'
import detailStyles from './NoteDetail.module.css'
import styles from './AssetViewer.module.css'

const HtmlSnapshotViewer = lazy(() => import('../HtmlSnapshotViewer/HtmlSnapshotViewer'))
const PDFViewer = lazy(() => import('../PDFViewer/PDFViewer'))

/** Extraction jobs that produce a tab, per object kind. */
const LINK_JOB_TABS: Array<{ kind: 'markdown' | 'pdf'; label: string }> = [
  { kind: 'markdown', label: 'MD' },
  { kind: 'pdf', label: 'PDF' },
]
const TEXT_JOB_TABS: Array<{ kind: 'markdown'; label: string }> = [{ kind: 'markdown', label: 'Текст' }]

const VIEW_ICON: Record<AssetViewKind, ReactNode> = {
  webpage_html: <Globe size={13} />,
  pdf: <FileDown size={13} />,
  markdown: <FileText size={13} />,
}

/** OCR / transcription / vision need the AI provider; document text extraction does not. */
function extractionNeedsAi(obj: NoteObject): boolean {
  return obj.type === 'image' || obj.type === 'audio' || obj.type === 'video'
}

function PanelLoader() {
  return <div className={styles.assetPanelLoader}><LoaderSpinner /></div>
}

function MarkdownSnapshotView({ src, fullscreen }: { src: string; fullscreen: boolean }) {
  const { data, isError } = useQuery({
    queryKey: ['snapshot-text', src],
    queryFn: async ({ signal }) => {
      const response = await apiFetch(src, { signal })
      if (!response.ok) throw new Error(`Markdown request failed with ${response.status}`)
      return response.text()
    },
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: 5 * 60_000,
  })
  if (isError) return <div className={styles.assetEmpty}>Не удалось загрузить Markdown</div>
  if (data === undefined) return <PanelLoader />
  return <pre className={fullscreen ? `${styles.assetMarkdown} ${styles.assetMarkdownFullscreen}` : styles.assetMarkdown}>{data}</pre>
}

function JobBadge({ job }: { job: SnapshotJob }) {
  if (job.status === 'failed') return <span className={styles.assetTabJobFailed} title="Ошибка">!</span>
  return <span className={styles.assetTabJobPct} title="Готовится">{job.status === 'processing' ? '50%' : '0%'}</span>
}

/**
 * Snapshot/extraction viewer of one object: tabs for the available renditions (website, PDF,
 * extracted text), progress of pending jobs, reprocess/download/fullscreen actions.
 */
export function AssetViewer({
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
  const aiEnabled = useAiEnabled()
  const canExtract = obj.type !== 'text' && (aiEnabled || !extractionNeedsAi(obj))
  const { views, jobs } = useObjectSnapshots(obj, noteId, obj.type !== 'text')
  const [activeKind, setActiveKind] = useState<AssetViewKind | null>(() => views[0]?.kind ?? null)
  const [fullscreenOpen, setFullscreenOpen] = useState(false)
  const favicon = useFavicon(obj.type === 'link' ? obj.content : null)
  const domain = obj.type === 'link' ? linkDomain(obj.content) : obj.content

  const markdownJob = jobs.find(job => job.job_type === 'markdown')
  const failedJob = jobs.find(job => job.status === 'failed' && job.error_message)
  const pendingTabs = (obj.type === 'link' ? LINK_JOB_TABS : TEXT_JOB_TABS).flatMap(tab => {
    if (views.some(view => view.kind === tab.kind)) return []
    const job = jobs.find(item => item.job_type === tab.kind)
    return job && !isFinishedJob(job) && job.status !== 'cancelled' ? [{ ...tab, job }] : []
  })

  const reprocess = useMutation({
    mutationFn: () => reprocessSnapshotMarkdown(noteId, obj.id),
    onSuccess: () => {
      setActiveKind('markdown')
      queryClient.invalidateQueries({ queryKey: ['snapshot-jobs', noteId] })
      requestChangeFeedSync()
      onOpen()
    },
  })

  const viewKey = views.map(view => view.kind).join('|')
  useEffect(() => {
    if (views.length === 0) setActiveKind(null)
    else if (!activeKind || !views.some(view => view.kind === activeKind)) setActiveKind(views[0].kind)
    // Re-evaluate only when the set of available views changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewKey])

  // Nothing to show at all (e.g. AI disabled and no extraction ever ran): hide the companion.
  if (!canExtract && views.length === 0 && jobs.length === 0 && obj.type !== 'link' && obj.type !== 'document') {
    return isEditing ? <button type="button" className={detailStyles.objDeleteBtn} onClick={onDelete}><X size={12} /></button> : null
  }

  const activeView: AssetView | null = views.find(view => view.kind === activeKind) ?? views[0] ?? null
  const title = obj.type === 'link'
    ? domain
    : extractionNeedsAi(obj)
      ? `Оцифровка · ${obj.filename ?? baseFileName(obj.filename)}`
      : baseFileName(obj.filename)
  const canOpenFullscreen = Boolean(activeView) || obj.type === 'link' || Boolean(markdownJob)

  function renderPreview(fullscreen: boolean): ReactNode {
    const emptyClassName = fullscreen ? `${styles.assetEmpty} ${styles.assetEmptyFullscreen}` : styles.assetEmpty
    if (activeView?.kind === 'webpage_html') {
      return (
        <Suspense fallback={<PanelLoader />}>
          <HtmlSnapshotViewer
            src={activeView.url}
            className={fullscreen ? `${styles.assetWebsiteFrame} ${styles.assetWebsiteFrameFullscreen}` : styles.assetWebsiteFrame}
          />
        </Suspense>
      )
    }
    if (activeView?.kind === 'pdf') {
      return <Suspense fallback={<PanelLoader />}><PDFViewer src={activeView.url} /></Suspense>
    }
    if (activeView?.kind === 'markdown') return <MarkdownSnapshotView src={activeView.url} fullscreen={fullscreen} />
    if (obj.type === 'link') {
      return (
        <div className={fullscreen ? `${styles.objLinkSnapshotPending} ${styles.objLinkSnapshotPendingFullscreen}` : styles.objLinkSnapshotPending}>
          {favicon && <img src={favicon} alt="" className={styles.objLinkSnapshotIcon} />}
          <div className={styles.objLinkSnapshotDomain}>{domain}</div>
          <div className={styles.objLinkSnapshotUrl}>{obj.content}</div>
          <div className={styles.objLinkSnapshotBadge}>
            {jobs.length > 0 && jobs.every(job => !isActiveJob(job)) ? 'снимок страницы недоступен' : 'снимок страницы готовится'}
          </div>
        </div>
      )
    }
    if (markdownJob?.status === 'failed') {
      return <div className={emptyClassName}>Оцифровка завершилась ошибкой: {markdownJob.error_message ?? 'нет деталей'}</div>
    }
    if (markdownJob && isActiveJob(markdownJob)) return <div className={emptyClassName}>Оцифровка готовится</div>
    if (!canExtract) return <div className={emptyClassName}>Оцифровка недоступна: ИИ отключён.</div>
    return <div className={emptyClassName}>Оцифровка еще не запускалась. Нажмите кнопку обновления выше.</div>
  }

  return (
    <div className={detailStyles.objWrapper}>
      <div className={isOpen ? styles.assetFrame : `${styles.assetFrame} ${styles.assetFrameCollapsed}`}>
        <div className={styles.assetChrome} onClick={onOpen}>
          {obj.type === 'link' && favicon && <img src={favicon} alt="" className={styles.objLinkFavicon} />}
          <span className={styles.assetTitle}>{title}</span>
          {(views.length > 1 || pendingTabs.length > 0) && (
            <div className={styles.assetTabs}>
              {views.map(view => {
                const job = obj.type === 'link' ? jobs.find(item => item.job_type === view.kind) : undefined
                return (
                  <button
                    key={view.kind}
                    type="button"
                    className={activeView?.kind === view.kind ? `${styles.assetTab} ${styles.assetTabActive}` : styles.assetTab}
                    onClick={event => {
                      event.stopPropagation()
                      setActiveKind(view.kind)
                      onOpen()
                    }}
                  >
                    {VIEW_ICON[view.kind]}
                    {view.label}
                    {job && isActiveJob(job) && <JobBadge job={job} />}
                    {job?.status === 'failed' && <JobBadge job={job} />}
                  </button>
                )
              })}
              {pendingTabs.map(tab => (
                <span
                  key={`job-${tab.kind}`}
                  className={styles.assetTabPending}
                  aria-label={tab.job.status === 'failed' ? `${tab.label}: ошибка` : `${tab.label}: готовится`}
                >
                  {VIEW_ICON[tab.kind]}
                  {tab.label}
                  <JobBadge job={tab.job} />
                </span>
              ))}
            </div>
          )}
          {canExtract && (
            <button
              type="button"
              className={styles.assetAction}
              disabled={reprocess.isPending || markdownJob?.status === 'processing'}
              onClick={event => {
                event.stopPropagation()
                reprocess.mutate()
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
                const ext = activeView.kind === 'markdown' ? 'md' : activeView.kind === 'webpage_html' ? 'html' : 'pdf'
                startDownload(activeView.url, `${obj.filename ? baseFileName(obj.filename) : obj.id}.${ext}`)
              }}
              title="Скачать текущий режим"
            >
              <Download size={13} />
            </button>
          )}
          {canOpenFullscreen && (
            <button
              type="button"
              className={styles.assetAction}
              onClick={event => {
                event.stopPropagation()
                onOpen()
                setFullscreenOpen(true)
              }}
              title="На весь экран"
            >
              <Maximize2 size={13} />
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
        {failedJob && (
          <div className={styles.assetErrorNotice} role="status">
            <AlertTriangle size={12} />
            <span>{failedJob.error_message}</span>
          </div>
        )}
        {reprocess.error && (
          <div className={styles.assetErrorNotice} role="status">
            <AlertTriangle size={12} />
            <span>{reprocess.error.message}</span>
          </div>
        )}
        {isOpen && (
          <div className={styles.assetBody}>
            <div className={styles.assetBodyInner} key={activeView ? `${activeView.kind}:${activeView.url}` : 'asset-view'}>
              {renderPreview(false)}
            </div>
          </div>
        )}
      </div>
      {fullscreenOpen && (
        <FullscreenDialog title={title} onClose={() => setFullscreenOpen(false)}>
          <div className={styles.assetFullscreenPreview}>{renderPreview(true)}</div>
        </FullscreenDialog>
      )}
      {isEditing && <button type="button" className={detailStyles.objDeleteBtn} onClick={onDelete}><X size={12} /></button>}
    </div>
  )
}
