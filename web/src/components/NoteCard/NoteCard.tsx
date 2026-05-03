import { useRef, useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { ExternalLink, FileText, ImageIcon, Link2, AlignLeft, Plus, UploadCloud, RefreshCw, Check } from 'lucide-react'
import { useSyncLocalNote } from '../../hooks/useSyncLocalNote'
import { useBulkSelect } from '../../contexts/BulkSelectContext'
import { draggable, dropTargetForElements } from '@atlaskit/pragmatic-drag-and-drop/element/adapter'
import { dropTargetForExternal } from '@atlaskit/pragmatic-drag-and-drop/external/adapter'
import { containsFiles, getFiles } from '@atlaskit/pragmatic-drag-and-drop/external/file'
import AuthImage from '../AuthImage/AuthImage'
import type { Note, NoteObject, Tag } from '../../types'
import { getTagColor } from '../../utils/tagColor'
import { MERGE_NOTES_ENABLED } from '../../api/notes'
import { useMergeNotes } from '../../hooks/useMergeNotes'
import { useUploadFiles } from '../../hooks/useUploadFiles'
import { useAddFilesToNote } from '../../hooks/useAddFilesToNote'
import { useCreateNote } from '../../hooks/useCreateNote'
import { useUpdateNote } from '../../hooks/useUpdateNote'
import { useDragContext } from '../../contexts/DragContext'
import { getObjectDisplayText, getObjectPreviewSource } from '../../utils/notePreview'
import { useFavicon } from '../../hooks/useFavicon'
import styles from './NoteCard.module.css'

const FILE_HOVER_THRESHOLD_MS = 750

// ─── Tags ─────────────────────────────────────────────────────────────────────

function TagList({ tags, onTagClick }: { tags: Tag[]; onTagClick?: (name: string) => void }) {
  if (tags.length === 0) return null
  return (
    <div className={styles.tags}>
      {tags.map(tag => {
        const { bg, text } = getTagColor(tag.name)
        return (
          <span
            key={tag.id}
            className={styles.tag}
            style={{ background: bg, color: text }}
            onClick={e => { e.preventDefault(); e.stopPropagation(); onTagClick?.(tag.name) }}
          >
            {tag.name}
          </span>
        )
      })}
    </div>
  )
}

// ─── Simple ──────────────────────────────────────────────────────────────────

function SimpleCard({ note, onTagClick }: { note: Note; onTagClick?: (name: string) => void }) {
  const imageObj = note.objects.find(o => o.type === 'image')
  const textObj  = note.objects.find(o => o.type === 'text')

  // Только картинка — без заголовка, изображение в край
  if (imageObj && !textObj) {
    const imageStyle = imageObj.imageWidth && imageObj.imageHeight
      ? { aspectRatio: `${imageObj.imageWidth} / ${imageObj.imageHeight}` }
      : undefined

    return (
      <Link draggable={false} to={`/notes/${note.slug}`} className={`${styles.card} ${styles.cardSimpleImage}`}>
        <AuthImage
          className={styles.simpleImageMedia}
          src={getObjectPreviewSource(imageObj)}
          alt={note.title}
          style={imageStyle}
        />
      </Link>
    )
  }

  return (
    <Link draggable={false} to={`/notes/${note.slug}`} className={`${styles.card} ${styles.cardSimple}`}>
      {imageObj && <AuthImage className={styles.cover} src={getObjectPreviewSource(imageObj)} alt="" />}
      <div className={styles.title}>{note.title}</div>
      {textObj && <div className={styles.excerpt}>{getObjectDisplayText(textObj)}</div>}
      <TagList tags={note.tags} onTagClick={onTagClick} />
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

// Фавиконка для одной ссылки (вынесена в отдельный компонент чтобы вызывать useFavicon)
function LinkFaviconItem({ url }: { url: string }) {
  const favicon = useFavicon(url)
  if (favicon) return <img src={favicon} alt="" className={styles.collectionLayerFavicon} />
  return <div className={styles.linkFaviconPlaceholder}><ExternalLink size={12} /></div>
}

// Контент одного слоя в стопке коллекции
function LayerContent({ obj, fallback }: { obj: NoteObject | undefined; fallback: string }) {
  if (!obj) {
    return <div className={styles.collectionLayerBg} style={{ background: fallback }} />
  }
  if (obj.type === 'image') {
    return <AuthImage src={getObjectPreviewSource(obj)} alt="" className={styles.collectionLayerImg} />
  }
  if (obj.type === 'document') {
    const thumb = obj.thumbnailUrl ?? obj.cover
    const thumbStyle = obj.imageWidth && obj.imageHeight ? { aspectRatio: `${obj.imageWidth}/${obj.imageHeight}` } : undefined
    if (thumb) return <AuthImage src={thumb} alt="" className={styles.collectionLayerImg} style={thumbStyle} />
    if (obj.thumbnailUrl === null) {
      return <div className={styles.thumbPending} style={thumbStyle} />
    }
    return (
      <div className={`${styles.collectionLayerBg} ${styles.collectionLayerDoc}`} style={{ background: fallback }}>
        <FileText size={24} />
      </div>
    )
  }
  if (obj.type === 'link') {
    if (obj.thumbnailUrl) {
      return <AuthImage src={obj.thumbnailUrl} alt="" className={styles.collectionLayerImg} />
    }
    return (
      <div className={`${styles.collectionLayerBg} ${styles.collectionLayerLink}`} style={{ background: fallback }}>
        <div className={styles.linkCoverInner}>
          <LinkFaviconItem url={obj.content} />
          <div className={styles.linkPendingSpinner} />
        </div>
      </div>
    )
  }
  return <div className={styles.collectionLayerBg} style={{ background: fallback }} />
}

const OBJECT_TYPE_ICON: Record<string, React.ReactNode> = {
  image:    <ImageIcon size={11} />,
  document: <FileText  size={11} />,
  link:     <Link2     size={11} />,
  text:     <AlignLeft size={11} />,
}

function CollectionStats({ objects }: { objects: Note['objects'] }) {
  const counts = objects.reduce<Record<string, number>>((acc, o) => {
    acc[o.type] = (acc[o.type] ?? 0) + 1
    return acc
  }, {})
  const order = ['image', 'document', 'link', 'text']
  const entries = order.filter(t => counts[t])

  return (
    <div className={styles.collectionStats}>
      {entries.map(type => (
        <span key={type} className={styles.collectionStat}>
          {OBJECT_TYPE_ICON[type]}
          {counts[type]}
        </span>
      ))}
    </div>
  )
}

function CollectionCard({ note, onTagClick, titleNode }: { note: Note; onTagClick?: (name: string) => void; titleNode?: React.ReactNode }) {
  const visualObjs = note.objects.filter(o => o.type === 'image' || o.type === 'document' || o.type === 'link').slice(0, 5)
  const fallback   = FALLBACK_COLORS[note.id.charCodeAt(0) % FALLBACK_COLORS.length]

  let visual: React.ReactNode

  if (visualObjs.length === 1) {
    const obj = visualObjs[0]
    if (obj.type === 'image') {
      visual = <AuthImage src={getObjectPreviewSource(obj)} alt="" className={styles.collectionSingle} />
    } else if (obj.type === 'link' && obj.thumbnailUrl) {
      visual = <AuthImage src={obj.thumbnailUrl} alt="" className={styles.collectionSingle} />
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
            ? <AuthImage key={obj.id} src={getObjectPreviewSource(obj)} alt="" className={styles.collectionPairImg} />
            : obj.type === 'link' && obj.thumbnailUrl
              ? <AuthImage key={obj.id} src={obj.thumbnailUrl} alt="" className={styles.collectionPairImg} />
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
        <CollectionStats objects={note.objects} />
        {titleNode}
        <TagList tags={note.tags} onTagClick={onTagClick} />
      </div>
    </Link>
  )
}

// ─── Composite ────────────────────────────────────────────────────────────────

function LinkChip({ obj }: { obj: NoteObject }) {
  const favicon = useFavicon(obj.content)
  let domain = ''
  try {
    domain = new URL(obj.content).hostname.replace(/^www\./, '')
  } catch { /* ignore */ }

  return (
    <div className={styles.linkChip}>
      <div className={styles.linkChipIcon}>
        {favicon
          ? <img src={favicon} alt="" className={styles.linkChipFavicon} />
          : <ExternalLink size={12} />
        }
      </div>
      <span className={styles.linkChipDomain}>{domain || obj.content}</span>
      <ExternalLink size={9} className={styles.linkChipArrow} />
    </div>
  )
}

function DocChip({ obj }: { obj: NoteObject }) {
  const label = obj.filename ?? obj.content
  const ext   = label.includes('.') ? label.split('.').pop()!.toUpperCase().slice(0, 4) : 'FILE'
  const name  = label.replace(/\.[^.]+$/, '')
  const thumb = obj.thumbnailUrl ?? obj.cover

  return (
    <div className={styles.docChip}>
      {thumb
        ? <AuthImage src={thumb} alt="" className={styles.docChipCover} />
        : <div className={styles.docChipIconWrap}>
            <FileText size={13} />
          </div>
      }
      <span className={styles.docChipName}>{name}</span>
      <span className={styles.docChipExt}>{ext}</span>
    </div>
  )
}

function CompositeCard({ note, onTagClick, titleNode }: { note: Note; onTagClick?: (name: string) => void; titleNode?: React.ReactNode }) {
  const imageObj  = note.objects.find(o => o.type === 'image')
  const textObj   = note.objects.find(o => o.type === 'text')
  const links     = note.objects.filter(o => o.type === 'link')
  const docs      = note.objects.filter(o => o.type === 'document')
  const firstDoc  = docs[0]
  const docThumb  = firstDoc ? (firstDoc.thumbnailUrl ?? firstDoc.cover) : undefined
  const firstLink = links[0]
  const firstLinkThumb = firstLink?.thumbnailUrl ?? null

  return (
    <Link draggable={false} to={`/notes/${note.slug}`} className={`${styles.card} ${styles.cardComposite}`}>

      {/* Cover */}
      <div className={styles.compositeCover}>
        {imageObj
          ? <AuthImage src={getObjectPreviewSource(imageObj)} alt="" className={styles.compositeCoverImg} />
          : docThumb
            ? <AuthImage src={docThumb} alt="" className={styles.compositeCoverImg} style={firstDoc?.imageWidth && firstDoc?.imageHeight ? { aspectRatio: `${firstDoc.imageWidth}/${firstDoc.imageHeight}` } : undefined} />
            : firstDoc?.thumbnailUrl === null
              ? <div className={styles.thumbPending} />
              : firstLink
                ? firstLinkThumb
                  ? <AuthImage src={firstLinkThumb} alt="" className={styles.compositeCoverImg} />
                  : (
                    <div className={styles.compositeCoverEmpty}>
                      <div className={styles.linkCoverInner}>
                        <div className={styles.linkFaviconRow}>
                          {links.slice(0, 4).map(l => <LinkFaviconItem key={l.id} url={l.content} />)}
                        </div>
                        {firstLink.thumbnailUrl === null && <div className={styles.linkPendingSpinner} />}
                      </div>
                    </div>
                  )
                : <div className={styles.compositeCoverEmpty}>
                    {textObj && <span className={styles.compositeCoverText}>{getObjectDisplayText(textObj, 240)}</span>}
                  </div>
        }
      </div>

      {/* Footer */}
      <div className={styles.cardFooter}>

        {/* Ссылки */}
        {links.length > 0 && (
          <div className={styles.compositeChips}>
            {links.map(o => <LinkChip key={o.id} obj={o} />)}
          </div>
        )}

        {/* Документы */}
        {docs.length > 0 && (
          <div className={styles.compositeChips}>
            {docs.map(o => <DocChip key={o.id} obj={o} />)}
          </div>
        )}

        {titleNode}
        {textObj && !/^https?:\/\//.test(textObj.content) && (
          <div className={styles.excerpt}>{getObjectDisplayText(textObj)}</div>
        )}
        <TagList tags={note.tags} onTagClick={onTagClick} />
      </div>
    </Link>
  )
}

// ─── DnD wrapper ──────────────────────────────────────────────────────────────

const HIGHLIGHT_MS = 5000

export function NoteCard({ note, isNew, onTagClick }: { note: Note; isNew?: boolean; onTagClick?: (tag: string) => void }) {
  const wrapperRef = useRef<HTMLDivElement>(null)
  const [isDragging,     setIsDragging]     = useState(false)
  const [isOver,         setIsOver]         = useState(false)
  const [fileHoverState, setFileHoverState] = useState<'new' | 'merge' | null>(null)

  // Rename after merge
  const [renamePending, setRenamePending] = useState(false)
  const [renameValue,   setRenameValue]   = useState('')
  const { mutate: updateNote } = useUpdateNote()

  // Стабильный ref для trigger-функции ренейма (используется внутри DnD useEffect)
  const triggerRenameRef = useRef<((initialValue?: string) => void) | null>(null)
  triggerRenameRef.current = (initialValue = '') => {
    setRenameValue(initialValue)
    setRenamePending(true)
  }

  function handleRenameSubmit() {
    const title = renameValue.trim() || note.title
    updateNote({ slug: note.slug, data: { title } })
    setRenamePending(false)
  }

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

  const { isBulk, selectedSlugs, toggleSelect } = useBulkSelect()
  const isSelected = selectedSlugs.has(note.slug)

  const { mutate: merge }    = useMergeNotes()
  const { mutate: upload }   = useUploadFiles()
  const { mutate: addFiles } = useAddFilesToNote()
  const { mutate: syncLocal, isPending: isSyncing } = useSyncLocalNote()

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
      getInitialData: () => ({ type: 'note', noteId: note.id, noteSlug: note.slug, noteType: note.type, noteTitle: note.title }),
      onDragStart: () => setIsDragging(true),
      onDrop: () => setIsDragging(false),
    })

    const cleanupDrop = dropTargetForElements({
      element: el,
      canDrop: ({ source }) =>
        MERGE_NOTES_ENABLED && source.data.type === 'note' && source.data.noteId !== note.id,
      onDragEnter: () => setIsOver(true),
      onDragLeave: () => setIsOver(false),
      onDrop: ({ source }) => {
        setIsOver(false)
        if (!MERGE_NOTES_ENABLED) return
        const sourceType  = source.data.noteType  as string
        const sourceTitle = source.data.noteTitle as string
        mergeRef.current(
          { sourceSlug: source.data.noteSlug as string, targetSlug: note.slug },
          {
            onSuccess: () => {
              const isMixed = (sourceType === 'collection') !== (note.type === 'collection')
              const prefill = isMixed
                ? (note.type === 'collection' ? note.title : sourceTitle)
                : ''
              triggerRenameRef.current?.(prefill)
            },
          },
        )
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
          uploadRef.current({ files })
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
    isSelected                 ? styles.isSelected      : '',
    note.isLoading             ? styles.isLoading       : '',
  ].filter(Boolean).join(' ')

  const titleNode = (
    <AnimatePresence mode="wait" initial={false}>
      {renamePending ? (
        <motion.div
          key="input"
          className={styles.renameRow}
          onClick={e => e.preventDefault()}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
        >
          <input
            autoFocus
            className={styles.renameInput}
            value={renameValue}
            onChange={e => setRenameValue(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') handleRenameSubmit()
              if (e.key === 'Escape') setRenamePending(false)
            }}
            placeholder="Название коллекции…"
          />
          <button className={styles.renameSubmit} onClick={e => { e.preventDefault(); handleRenameSubmit() }}>
            ↵
          </button>
        </motion.div>
      ) : (
        <motion.div
          key="title"
          className={styles.title}
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
        >
          {note.title}
        </motion.div>
      )}
    </AnimatePresence>
  )

  return (
    <div ref={wrapperRef} className={cls} style={{ position: 'relative' }}>
      {note.type === 'collection' ? (
        <CollectionCard note={note} onTagClick={onTagClick} titleNode={titleNode} />
      ) : note.type === 'composite' ? (
        <CompositeCard  note={note} onTagClick={onTagClick} titleNode={titleNode} />
      ) : (
        <SimpleCard note={note} onTagClick={onTagClick} />
      )}
      {isBulk && (
        <div
          className={styles.bulkOverlay}
          onClick={e => { e.preventDefault(); e.stopPropagation(); toggleSelect(note.slug) }}
        >
          <div className={`${styles.bulkCheck} ${isSelected ? styles.bulkCheckActive : ''}`}>
            {isSelected && <Check size={12} strokeWidth={3} />}
          </div>
        </div>
      )}
      {note.isLocal && (
        <button
          className={`${styles.syncBtn}${isSyncing ? ` ${styles.syncing}` : ''}`}
          title="Синхронизировать с сервером"
          onClick={e => { e.preventDefault(); e.stopPropagation(); syncLocal(note) }}
        >
          <RefreshCw size={14} />
        </button>
      )}
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
        if (dropped.length > 0) upload({ files: dropped })
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
      // Файлы (возможно + текст) → один джоб
      upload({ files, text: trimmed || undefined })
    } else {
      // Только текст → обычное создание
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
