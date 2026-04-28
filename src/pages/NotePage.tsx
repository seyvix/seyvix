import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, ExternalLink, FileText, Download, X } from 'lucide-react'
import { useNote } from '../hooks/useNote'
import { useUpdateNote } from '../hooks/useUpdateNote'
import { getTagColor } from '../utils/tagColor'
import AuthImage from '../components/AuthImage/AuthImage'
import type { Note, NoteObject, Tag } from '../types'
import styles from './NotePage.module.css'

// ─── Object renderers ──────────────────────────────────────────────────────────

function ImageObj({ obj, isEditing, onDelete }: { obj: NoteObject; isEditing: boolean; onDelete: () => void }) {
  return (
    <div className={`${styles.objWrapper} ${styles.objImage}`}>
      <AuthImage src={obj.content} alt="" style={{ cursor: 'pointer' }} onClick={() => window.open(obj.content, '_blank')} />
      {isEditing && (
        <button className={styles.objDeleteBtn} onClick={onDelete}><X size={12} /></button>
      )}
    </div>
  )
}

function makeLinkSrcdoc(url: string, domain: string, faviconUrl: string): string {
  const escaped = url.replace(/"/g, '&quot;')
  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  background: #0f0f0f;
  color: #f5f5f5;
  height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  user-select: none;
}
img { width: 48px; height: 48px; border-radius: 10px; }
.domain { font-size: 22px; font-weight: 600; color: #e5e5e5; }
.url { font-size: 12px; color: #555; max-width: 320px; text-align: center; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.badge { font-size: 10px; color: #444; border: 1px solid #2a2a2a; border-radius: 20px; padding: 3px 10px; margin-top: 8px; }
</style>
</head>
<body>
  <img src="https://www.google.com/s2/favicons?domain=${domain}&sz=96" onerror="this.style.display='none'" />
  <div class="domain">${domain}</div>
  <div class="url">${escaped}</div>
  <div class="badge">снапшот</div>
</body>
</html>`
}

function LinkObj({ obj, isEditing, onDelete }: { obj: NoteObject; isEditing: boolean; onDelete: () => void }) {
  let domain = obj.content
  let favicon = ''
  try {
    const u = new URL(obj.content)
    domain  = u.hostname.replace(/^www\./, '')
    favicon = `https://www.google.com/s2/favicons?domain=${u.hostname}&sz=32`
  } catch { /* ignore */ }

  const srcdoc = makeLinkSrcdoc(obj.content, domain, favicon)

  return (
    <div className={styles.objWrapper}>
      <div className={styles.objLinkFrame}>
        {/* Mini browser chrome */}
        <div className={styles.objLinkChrome}>
          {favicon && <img src={favicon} alt="" className={styles.objLinkFavicon} />}
          <span className={styles.objLinkChromeDomain}>{domain}</span>
          <a
            className={styles.objLinkChromeOpen}
            href={obj.content}
            target="_blank"
            rel="noopener noreferrer"
            title="Открыть сайт"
          >
            <ExternalLink size={13} />
          </a>
        </div>
        {/* Snapshot iframe */}
        <iframe
          className={styles.objLinkIframe}
          srcDoc={srcdoc}
          sandbox="allow-same-origin"
          title={domain}
        />
      </div>
      {isEditing && (
        <button className={styles.objDeleteBtn} onClick={onDelete}><X size={12} /></button>
      )}
    </div>
  )
}

function DocObj({ obj, isEditing, onDelete }: { obj: NoteObject; isEditing: boolean; onDelete: () => void }) {
  const ext  = obj.content.includes('.') ? obj.content.split('.').pop()!.toUpperCase().slice(0, 4) : 'FILE'
  const name = obj.content.replace(/\.[^.]+$/, '')

  return (
    <div className={styles.objWrapper}>
      <div className={styles.objDoc}>
        {obj.cover
          ? <AuthImage src={obj.cover} alt="" className={styles.objDocCover} />
          : <div className={styles.objDocIconWrap}><FileText size={20} /></div>
        }
        <div className={styles.objDocMeta}>
          <div className={styles.objDocName}>{name}</div>
          <span className={styles.objDocExt}>{ext}</span>
        </div>
        <Download size={16} className={styles.objDocDownload} />
      </div>
      {isEditing && (
        <button className={styles.objDeleteBtn} onClick={onDelete}><X size={12} /></button>
      )}
    </div>
  )
}

function TextObj({
  obj,
  isEditing,
  editValue,
  onChangeEdit,
  onDelete,
}: {
  obj: NoteObject
  isEditing: boolean
  editValue: string
  onChangeEdit: (v: string) => void
  onDelete: () => void
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

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function NotePage() {
  const { noteSlug } = useParams<{ noteSlug: string }>()
  const navigate = useNavigate()
  const { data: note, isLoading } = useNote(noteSlug!)
  const { mutate: updateNote } = useUpdateNote()

  const [isEditing,   setIsEditing]   = useState(false)
  const [editTitle,   setEditTitle]   = useState('')
  const [editTexts,   setEditTexts]   = useState<Record<string, string>>({})
  const [deletedObjs, setDeletedObjs] = useState<Set<string>>(new Set())

  function enterEdit() {
    if (!note) return
    setEditTitle(note.title)
    const texts: Record<string, string> = {}
    note.objects.filter(o => o.type === 'text').forEach(o => { texts[o.id] = o.content })
    setEditTexts(texts)
    setDeletedObjs(new Set())
    setIsEditing(true)
  }

  function cancelEdit() {
    setIsEditing(false)
  }

  function saveEdit() {
    if (!note) return
    const objects = note.objects
      .filter(o => !deletedObjs.has(o.id))
      .map(o => o.type === 'text' ? { ...o, content: editTexts[o.id] ?? o.content } : o)
    updateNote({ slug: note.slug, data: { title: editTitle || note.title, objects } })
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

  const formattedDate = new Date(note.updatedAt).toLocaleDateString('ru-RU', {
    day: 'numeric', month: 'long', year: 'numeric',
  })

  return (
    <div className={styles.page}>
      <div className={styles.topBar}>
        <button className={styles.backBtn} onClick={() => navigate(-1)}>
          <ArrowLeft size={14} />
          Заметки
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

      <div className={styles.content}>
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
          </div>
        </div>

        <div className={styles.stream}>
          {visibleObjects.map(obj => {
            if (obj.type === 'image') return (
              <ImageObj key={obj.id} obj={obj} isEditing={isEditing} onDelete={() => setDeletedObjs(p => new Set([...p, obj.id]))} />
            )
            if (obj.type === 'link') return (
              <LinkObj key={obj.id} obj={obj} isEditing={isEditing} onDelete={() => setDeletedObjs(p => new Set([...p, obj.id]))} />
            )
            if (obj.type === 'document') return (
              <DocObj key={obj.id} obj={obj} isEditing={isEditing} onDelete={() => setDeletedObjs(p => new Set([...p, obj.id]))} />
            )
            if (obj.type === 'text') return (
              <TextObj
                key={obj.id}
                obj={obj}
                isEditing={isEditing}
                editValue={editTexts[obj.id] ?? obj.content}
                onChangeEdit={v => setEditTexts(p => ({ ...p, [obj.id]: v }))}
                onDelete={() => setDeletedObjs(p => new Set([...p, obj.id]))}
              />
            )
            return null
          })}
        </div>
      </div>
    </div>
  )
}
