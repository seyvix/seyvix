import { useRef, useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { ExternalLink, FileText, Plus, UploadCloud } from 'lucide-react'
import { draggable, dropTargetForElements } from '@atlaskit/pragmatic-drag-and-drop/element/adapter'
import { dropTargetForExternal } from '@atlaskit/pragmatic-drag-and-drop/external/adapter'
import { containsFiles, getFiles } from '@atlaskit/pragmatic-drag-and-drop/external/file'
import type { Note, NoteObject } from '../../types'
import { useMergeNotes } from '../../hooks/useMergeNotes'
import { useUploadFiles } from '../../hooks/useUploadFiles'
import { useAddFilesToNote } from '../../hooks/useAddFilesToNote'
import { useCreateNote } from '../../hooks/useCreateNote'
import { useDragContext } from '../../contexts/DragContext'
import styles from './NoteCard.module.css'

const FILE_HOVER_THRESHOLD_MS = 750

// ─── Simple ──────────────────────────────────────────────────────────────────

function SimpleCard({ note }: { note: Note }) {
  const imageObj = note.objects.find(o => o.type === 'image')
  const textObj  = note.objects.find(o => o.type === 'text')

  // Только картинка — без заголовка, изображение в край
  if (imageObj && !textObj) {
    return (
      <Link draggable={false} to={`/notes/${note.slug}`} className={`${styles.card} ${styles.cardSimpleImage}`}>
        <img src={imageObj.content} alt={note.title} />
      </Link>
    )
  }

  return (
    <Link draggable={false} to={`/notes/${note.slug}`} className={`${styles.card} ${styles.cardSimple}`}>
      {imageObj && <img className={styles.cover} src={imageObj.content} alt="" />}
      <div className={styles.title}>{note.title}</div>
      {textObj && <div className={styles.excerpt}>{textObj.content}</div>}
      {note.tags.length > 0 && (
        <div className={styles.tags}>
          {note.tags.map(tag => <span key={tag.id} className={styles.tag}>{tag.name}</span>)}
        </div>
      )}
    </Link>
  )
}

// ─── Collection ───────────────────────────────────────────────────────────────

// Стопка всегда занимает одну и ту же площадь (STACK_W × STACK_H).
// При меньшем количестве слоёв каждая карточка становится крупнее.
// index 0 = задний слой, index layerCount-1 = передний.
function buildLayerPositions(layerCount: number) {
  const STACK_W = 92
  const STACK_H = 92
  const DX      = 3
  const DY      = 3
  const cardW   = STACK_W - (layerCount - 1) * DX
  const cardH   = STACK_H - (layerCount - 1) * DY
  const stackLeft = (100 - STACK_W) / 2
  const stackTop  = (100 - STACK_H) / 2

  return Array.from({ length: layerCount }, (_, i) => {
    const depth = layerCount - 1 - i
    return {
      left:    `${stackLeft + depth * DX}%`,
      top:     `${stackTop  + depth * DY}%`,
      width:   `${cardW}%`,
      height:  `${cardH}%`,
      zIndex:  i + 1,
      opacity: layerCount === 1 ? 1 : 0.6 + (i / (layerCount - 1)) * 0.4,
    }
  })
}

const FALLBACK_COLORS = ['#1e3a2a', '#1e2a3a', '#2e1e3a', '#3a2e1e']

// Контент одного слоя в стопке коллекции
function LayerContent({ obj, fallback }: { obj: NoteObject | undefined; fallback: string }) {
  if (!obj) {
    return <div className={styles.collectionLayerBg} style={{ background: fallback }} />
  }
  if (obj.type === 'image') {
    return <img src={obj.content} alt="" className={styles.collectionLayerImg} />
  }
  if (obj.type === 'document') {
    if (obj.cover) return <img src={obj.cover} alt="" className={styles.collectionLayerImg} />
    return (
      <div className={`${styles.collectionLayerBg} ${styles.collectionLayerDoc}`} style={{ background: fallback }}>
        <FileText size={24} />
      </div>
    )
  }
  if (obj.type === 'link') {
    let favicon: string | null = null
    try {
      const domain = new URL(obj.content).hostname
      favicon = `https://www.google.com/s2/favicons?domain=${domain}&sz=64`
    } catch { /* ignore */ }
    return (
      <div className={`${styles.collectionLayerBg} ${styles.collectionLayerLink}`} style={{ background: fallback }}>
        {favicon
          ? <img src={favicon} alt="" className={styles.collectionLayerFavicon} />
          : <ExternalLink size={20} />
        }
      </div>
    )
  }
  return <div className={styles.collectionLayerBg} style={{ background: fallback }} />
}

function CollectionCard({ note }: { note: Note }) {
  const count      = note.objects.length
  // image, document, link — всё что можно показать в слоях
  const visualObjs = note.objects.filter(o => o.type === 'image' || o.type === 'document' || o.type === 'link').slice(0, 5)
  const fallback   = FALLBACK_COLORS[note.id.charCodeAt(0) % FALLBACK_COLORS.length]

  let visual: React.ReactNode

  if (visualObjs.length === 1) {
    const obj = visualObjs[0]
    if (obj.type === 'image') {
      visual = <img src={obj.content} alt="" className={styles.collectionSingle} />
    } else {
      visual = (
        <div className={styles.collectionSingleNonImage}>
          <LayerContent obj={obj} fallback={fallback} />
        </div>
      )
    }
  } else if (visualObjs.length === 2) {
    visual = (
      <div className={styles.collectionPair}>
        {visualObjs.map(obj => (
          obj.type === 'image'
            ? <img key={obj.id} src={obj.content} alt="" className={styles.collectionPairImg} />
            : <div key={obj.id} className={styles.collectionPairSlot}>
                <LayerContent obj={obj} fallback={fallback} />
              </div>
        ))}
      </div>
    )
  } else {
    const layerCount = Math.min(5, Math.max(1, visualObjs.length))
    const positions  = buildLayerPositions(layerCount)

    visual = positions.map((pos, i) => {
      const obj     = visualObjs[layerCount - 1 - i]
      const isFront = i === layerCount - 1

      return (
        <div
          key={i}
          className={styles.collectionLayer}
          style={{ width: pos.width, height: pos.height, left: pos.left, top: pos.top, zIndex: pos.zIndex }}
        >
          <LayerContent obj={obj} fallback={fallback} />
          {isFront && count > 1 && (
            <div className={styles.collectionBadge}>{count}</div>
          )}
        </div>
      )
    })
  }

  return (
    <Link draggable={false} to={`/notes/${note.slug}`} className={`${styles.card} ${styles.cardCollection}`}>
      <div className={styles.collectionVisual}>
        {visual}
      </div>
      <div className={styles.cardFooter}>
        <div className={styles.title}>{note.title}</div>
        {note.tags.length > 0 && (
          <div className={styles.tags}>
            {note.tags.map(tag => <span key={tag.id} className={styles.tag}>{tag.name}</span>)}
          </div>
        )}
      </div>
    </Link>
  )
}

// ─── Composite ────────────────────────────────────────────────────────────────

function Panel({ obj, area }: { obj: NoteObject; area: string }) {
  const style: React.CSSProperties = { gridArea: area }

  if (obj.type === 'image') {
    return (
      <div className={`${styles.panel} ${styles.panelImage}`} style={style}>
        <img src={obj.content} alt="" />
      </div>
    )
  }

  if (obj.type === 'text') {
    return (
      <div className={`${styles.panel} ${styles.panelText}`} style={style}>
        <span className={styles.panelTextContent}>{obj.content}</span>
      </div>
    )
  }

  if (obj.type === 'link') {
    let favicon: string | null = null
    try {
      const domain = new URL(obj.content).hostname
      favicon = `https://www.google.com/s2/favicons?domain=${domain}&sz=64`
    } catch {
      // невалидный URL — покажем заглушку
    }

    return (
      <div className={`${styles.panel} ${styles.panelLink}`} style={style}>
        {favicon
          ? <div className={styles.panelFaviconWrap}>
              <img src={favicon} alt="" className={styles.panelFavicon} />
            </div>
          : <div className={styles.panelLinkIcon}>
              <ExternalLink size={14} />
            </div>
        }
        <div className={styles.panelLinkArrow}>
          <ExternalLink size={9} />
        </div>
      </div>
    )
  }

  if (obj.cover) {
    return (
      <div className={`${styles.panel} ${styles.panelImage}`} style={style}>
        <img src={obj.cover} alt="" />
      </div>
    )
  }

  return (
    <div className={`${styles.panel} ${styles.panelDocument}`} style={style}>
      <div className={styles.panelDocIcon}>
        <FileText size={20} />
      </div>
    </div>
  )
}

const GRID_TEMPLATES: Record<number, string> = {
  1: '"a"',
  2: '"a b"',
  3: '"a b" "a c"',
  4: '"a b" "c d"',
}

function CompositeCard({ note }: { note: Note }) {
  const slots = note.objects.filter(o => o.type !== 'text').slice(0, 4)
  const areas = GRID_TEMPLATES[Math.max(1, slots.length)] ?? GRID_TEMPLATES[4]

  return (
    <Link draggable={false} to={`/notes/${note.slug}`} className={`${styles.card} ${styles.cardComposite}`}>
      <div className={styles.compositeGrid} style={{ gridTemplateAreas: areas }}>
        {slots.map((obj, i) => (
          <Panel key={obj.id} obj={obj} area={String.fromCharCode(97 + i)} />
        ))}
      </div>
      <div className={styles.cardFooter}>
        <div className={styles.footerMeta}>{note.objects.length} объектов</div>
        <div className={styles.title}>{note.title}</div>
        {note.tags.length > 0 && (
          <div className={styles.tags}>
            {note.tags.map(tag => <span key={tag.id} className={styles.tag}>{tag.name}</span>)}
          </div>
        )}
      </div>
    </Link>
  )
}

// ─── DnD wrapper ──────────────────────────────────────────────────────────────

const HIGHLIGHT_MS = 5000

export function NoteCard({ note, isNew }: { note: Note; isNew?: boolean }) {
  const wrapperRef = useRef<HTMLDivElement>(null)
  const [isDragging,     setIsDragging]     = useState(false)
  const [isOver,         setIsOver]         = useState(false)
  const [fileHoverState, setFileHoverState] = useState<'new' | 'merge' | null>(null)

  // Подсветка: если заметка создана меньше HIGHLIGHT_MS назад — подсвечиваем
  const age = Date.now() - new Date(note.createdAt).getTime()
  const [highlighted, setHighlighted] = useState(() => age < HIGHLIGHT_MS)

  useEffect(() => {
    if (!highlighted) return
    const remaining = HIGHLIGHT_MS - (Date.now() - new Date(note.createdAt).getTime())
    if (remaining <= 0) { setHighlighted(false); return }
    const t = setTimeout(() => setHighlighted(false), remaining)
    return () => clearTimeout(t)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const { mutate: merge }    = useMergeNotes()
  const { mutate: upload }   = useUploadFiles()
  const { mutate: addFiles } = useAddFilesToNote()

  // Стабильные рефы, чтобы useEffect не переподписывался на каждый рендер
  const mergeRef    = useRef(merge)
  const uploadRef   = useRef(upload)
  const addFilesRef = useRef(addFiles)
  useEffect(() => { mergeRef.current    = merge    })
  useEffect(() => { uploadRef.current   = upload   })
  useEffect(() => { addFilesRef.current = addFiles })

  const dragEnterTimeRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    const el = wrapperRef.current
    if (!el) return

    const cleanupDrag = draggable({
      element: el,
      getInitialData: () => ({ type: 'note', noteId: note.id }),
      onDragStart: () => setIsDragging(true),
      onDrop: () => setIsDragging(false),
    })

    const cleanupDrop = dropTargetForElements({
      element: el,
      canDrop: ({ source }) =>
        source.data.type === 'note' && source.data.noteId !== note.id,
      onDragEnter: () => setIsOver(true),
      onDragLeave: () => setIsOver(false),
      onDrop: ({ source }) => {
        setIsOver(false)
        mergeRef.current({ sourceId: source.data.noteId as string, targetId: note.id })
      },
    })

    const cleanupFileDrop = dropTargetForExternal({
      element: el,
      canDrop: containsFiles,
      onDragEnter: () => {
        dragEnterTimeRef.current = Date.now()
        setFileHoverState('new')
        timerRef.current = setTimeout(() => setFileHoverState('merge'), FILE_HOVER_THRESHOLD_MS)
      },
      onDragLeave: () => {
        if (timerRef.current) clearTimeout(timerRef.current)
        setFileHoverState(null)
      },
      onDrop: ({ source }) => {
        if (timerRef.current) clearTimeout(timerRef.current)
        const elapsed = Date.now() - dragEnterTimeRef.current
        const files = getFiles({ source })
        setFileHoverState(null)
        if (files.length === 0) return
        if (elapsed < FILE_HOVER_THRESHOLD_MS) {
          uploadRef.current(files)
        } else {
          addFilesRef.current({ noteId: note.id, files })
        }
      },
    })

    return () => {
      cleanupDrag()
      cleanupDrop()
      cleanupFileDrop()
    }
  }, [note.id])

  const cls = [
    styles.cardWrapper,
    isDragging                 ? styles.isDragging      : '',
    isOver                     ? styles.isDropOver      : '',
    fileHoverState === 'new'   ? styles.isFileOverNew   : '',
    fileHoverState === 'merge' ? styles.isFileOverMerge : '',
    highlighted                ? styles.isHighlighted   : '',
  ].filter(Boolean).join(' ')

  return (
    <div ref={wrapperRef} className={cls}>
      {note.type === 'collection' ? <CollectionCard note={note} />
      : note.type === 'composite'  ? <CompositeCard  note={note} />
      :                              <SimpleCard      note={note} />}
    </div>
  )
}

// ─── Add card ─────────────────────────────────────────────────────────────────

export function AddNoteCard({ onClick }: { onClick?: () => void }) {
  const dropRef  = useRef<HTMLDivElement>(null)
  const textaRef = useRef<HTMLTextAreaElement>(null)

  const [isOver,    setIsOver]    = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [text,      setText]      = useState('')
  const [files,     setFiles]     = useState<File[]>([])

  const { mutate: upload } = useUploadFiles()
  const { mutate: create } = useCreateNote()
  const { isFileDragging } = useDragContext()

  useEffect(() => {
    const el = dropRef.current
    if (!el) return
    return dropTargetForExternal({
      element: el,
      canDrop: containsFiles,
      onDragEnter: () => setIsOver(true),
      onDragLeave: () => setIsOver(false),
      onDrop: ({ source }) => {
        setIsOver(false)
        // DnD-дроп всегда создаёт новую заметку сразу
        const dropped = getFiles({ source })
        if (dropped.length > 0) upload(dropped)
      },
    })
  }, [upload])

  useEffect(() => {
    if (isEditing) textaRef.current?.focus()
  }, [isEditing])

  function handleOpen() {
    setIsEditing(true)
    onClick?.()
  }

  function handleCancel() {
    setIsEditing(false)
    setText('')
    setFiles([])
  }

  function handleSubmit() {
    const trimmed = text.trim()
    const hasFiles = files.length > 0

    if (!trimmed && !hasFiles) { handleCancel(); return }

    if (hasFiles) {
      upload(files)
    }
    if (trimmed) {
      const title = trimmed.split('\n')[0].slice(0, 60) || 'Новая заметка'
      create({
        title,
        type: 'simple',
        objects: [{ id: `txt-${Date.now()}`, type: 'text', content: trimmed, createdAt: new Date().toISOString() }],
      })
    }
    handleCancel()
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Escape') { handleCancel(); return }
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit()
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(e.target.files ?? [])
    if (picked.length > 0) setFiles(prev => [...prev, ...picked])
    e.target.value = ''
  }

  function removeFile(idx: number) {
    setFiles(prev => prev.filter((_, i) => i !== idx))
  }

  const showFileMode = (isFileDragging || isOver) && !isEditing

  const wrapperCls = [
    styles.addCard,
    isEditing                    ? styles.addCardEditing   : '',
    isOver && !isEditing         ? styles.addCardOver      : '',
    isFileDragging && !isEditing ? styles.addCardFileDrag  : '',
  ].filter(Boolean).join(' ')

  return (
    <div ref={dropRef} className={wrapperCls}>
      {isEditing ? (
        <>
          <textarea
            ref={textaRef}
            className={styles.addCardTextarea}
            placeholder="Что у вас на уме?"
            value={text}
            onChange={e => setText(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          {files.length > 0 && (
            <ul className={styles.addCardFileList}>
              {files.map((f, i) => (
                <li key={i} className={styles.addCardFileItem}>
                  <span className={styles.addCardFileName}>{f.name}</span>
                  <button className={styles.addCardFileRemove} onClick={() => removeFile(i)}>✕</button>
                </li>
              ))}
            </ul>
          )}
          <div className={styles.addCardActions}>
            <label className={styles.addCardFileBtn} title="Прикрепить файл">
              <Plus size={15} />
              <input type="file" multiple hidden onChange={handleFileChange} />
            </label>
            <button className={styles.addCardCancelBtn} onClick={handleCancel}>Отмена</button>
            <button className={styles.addCardSubmitBtn} onClick={handleSubmit}>Создать</button>
          </div>
        </>
      ) : (
        <button className={styles.addCardTrigger} onClick={handleOpen}>
          {showFileMode
            ? <UploadCloud size={28} className={styles.addIcon} />
            : <Plus size={20} className={styles.addIcon} />
          }
          {isOver ? 'Отпустите файлы' : showFileMode ? 'Бросьте сюда' : 'Добавить заметку'}
        </button>
      )}
    </div>
  )
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────

export function SkeletonCard() {
  return <div className={styles.skeletonCard} />
}
