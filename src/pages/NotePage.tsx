import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, ExternalLink, FileText, Download, X, ChevronRight } from 'lucide-react'
import { useNote } from '../hooks/useNote'
import { useUpdateNote } from '../hooks/useUpdateNote'
import { useRemoveCollectionItems } from '../hooks/useRemoveCollectionItems'
import { getTagColor } from '../utils/tagColor'
import AuthImage from '../components/AuthImage/AuthImage'
import { apiFetch } from '../lib/apiClient'
import type { Note, NoteObject, Tag } from '../types'
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
  return <p className={styles.objText}>{obj.content}</p>
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
            {hint}
            {removeBtn}
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
              return null
            })}
          </div>
        )}

      </div>
    </div>
  )
}
