import { useRef, useState, useEffect, useCallback, type CSSProperties } from 'react'
import { Link } from 'react-router'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { EditorContent, useEditor, type Editor } from '@tiptap/react'
import { BubbleMenu } from '@tiptap/react/menus'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import TaskList from '@tiptap/extension-task-list'
import TaskItem from '@tiptap/extension-task-item'
import Image from '@tiptap/extension-image'
import LinkExtension from '@tiptap/extension-link'
import Typography from '@tiptap/extension-typography'
import UnderlineExtension from '@tiptap/extension-underline'
import {
  AlignLeft,
  Bold,
  Check,
  Code2,
  ExternalLink,
  FileText,
  Heading1,
  ImageIcon,
  Italic,
  Link2,
  List,
  ListChecks,
  ListOrdered,
  Minus,
  Paperclip,
  Plus,
  RefreshCw,
  Send,
  TextQuote,
  Underline,
  UploadCloud,
} from 'lucide-react'
import { useSyncLocalNote } from '../../hooks/useSyncLocalNote'
import { useBulkSelect } from '../../contexts/BulkSelectContext'
import { dropTargetForExternal } from '@atlaskit/pragmatic-drag-and-drop/external/adapter'
import { containsFiles, getFiles } from '@atlaskit/pragmatic-drag-and-drop/external/file'
import AuthImage from '../AuthImage/AuthImage'
import { LoaderSpinner } from '../LoaderSpinner'
import type { Note, NoteObject, Tag } from '../../types'
import { getTagColor } from '../../utils/tagColor'
import { useUploadFiles } from '../../hooks/useUploadFiles'
import { useAddFilesToNote } from '../../hooks/useAddFilesToNote'
import { useCreateNote } from '../../hooks/useCreateNote'
import { useUpdateNote } from '../../hooks/useUpdateNote'
import { useDragContext } from '../../contexts/DragContext'
import { useUploadContext } from '../../contexts/UploadContext'
import { partitionUploadFiles } from '../../utils/uploadGuard'
import { getObjectDisplayText, getObjectPreviewSource } from '../../utils/notePreview'
import { collectSourceChips, getSavedDateLabel } from '../../utils/noteCardPresentation'
import { normalizedHighlightRanges } from '../../utils/searchHighlight'
import { htmlToMarkdown, makeMarkdownTitle, replaceBlobImageSources } from '../../utils/markdownPaste'
import { useFavicon } from '../../hooks/useFavicon'
import styles from './NoteCard.module.css'

const FILE_HOVER_THRESHOLD_MS = 750

function notePageHref(note: Note): string {
  if (note.isLocal || note.isLoading) return '/notes'
  return `/notes/${note.id}`
}

// ─── Tags ─────────────────────────────────────────────────────────────────────

function SourceChipList({ note }: { note: Note }) {
  const chips = collectSourceChips(note)
  if (chips.length === 0) return null
  return (
    <>
      {chips.map(chip => (
        <span key={chip.key} className={styles.sourceTag} title={chip.title}>
          <Send size={10} />
          <span className={styles.sourceProvider}>{chip.providerLabel}</span>
          {chip.originLabel && <span className={styles.sourceOrigin}>{chip.originLabel}</span>}
        </span>
      ))}
    </>
  )
}

function TagList({ tags, onTagClick, max = 4 }: { tags: Tag[]; onTagClick?: (name: string) => void; max?: number }) {
  if (tags.length === 0) return null
  const visibleTags = tags.slice(0, max)
  const hiddenCount = Math.max(0, tags.length - visibleTags.length)

  return (
    <>
      {visibleTags.map(tag => {
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
      {hiddenCount > 0 && <span className={styles.moreTag}>+{hiddenCount}</span>}
    </>
  )
}

function CardMeta({ note, onTagClick, maxTags = 4 }: { note: Note; onTagClick?: (name: string) => void; maxTags?: number }) {
  const hasSources = collectSourceChips(note).length > 0
  if (!hasSources && note.tags.length === 0) return null
  return (
    <div className={styles.tags}>
      <SourceChipList note={note} />
      <TagList tags={note.tags} onTagClick={onTagClick} max={maxTags} />
    </div>
  )
}

function SavedDate({ note, tone = 'muted' }: { note: Note; tone?: 'muted' | 'overlay' }) {
  const label = getSavedDateLabel(note.createdAt)
  if (!label) return null
  return <span className={`${styles.savedDate} ${tone === 'overlay' ? styles.savedDateOverlay : ''}`}>{label}</span>
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function getObjectAspectRatio(obj: NoteObject | undefined): number | null {
  if (!obj?.imageWidth || !obj.imageHeight) return null
  return clamp(obj.imageWidth / obj.imageHeight, 0.68, 1.55)
}

function visualRatioStyle(obj: NoteObject | undefined, fallbackRatio: number): CSSProperties {
  return { '--note-card-visual-ratio': String(getObjectAspectRatio(obj) ?? fallbackRatio) } as CSSProperties
}

function textDensityClass(text: string | null | undefined): string {
  const length = (text ?? '').trim().length
  if (length < 90) return styles.cardTextShort
  if (length > 280) return styles.cardTextLong
  return styles.cardTextMedium
}

function SearchMatchSnippet({ note }: { note: Note }) {
  const match = note.searchMatches?.[0]
  if (!match?.text) return null
  const ranges = normalizedHighlightRanges(match)
  const parts: React.ReactNode[] = []
  let cursor = 0

  for (const range of ranges.slice(0, 6)) {
    if (range.start > cursor) {
      parts.push(match.text.slice(cursor, range.start))
    }
    parts.push(<mark key={`${range.start}-${range.end}`}>{match.text.slice(range.start, range.end)}</mark>)
    cursor = range.end
  }
  if (cursor < match.text.length) parts.push(match.text.slice(cursor))

  return <div className={styles.searchSnippet}>{parts.length ? parts : match.text}</div>
}

function SoftOverlay({
  note,
  titleNode,
  description,
  children,
  onTagClick,
}: {
  note: Note
  titleNode?: React.ReactNode
  description?: React.ReactNode
  children?: React.ReactNode
  onTagClick?: (name: string) => void
}) {
  return (
    <div className={styles.softOverlay}>
      <div className={styles.softOverlayTop}>
        <SavedDate note={note} tone="overlay" />
        {children}
      </div>
      {titleNode ?? <div className={styles.title}>{note.title}</div>}
      {description && <div className={styles.overlayExcerpt}>{description}</div>}
      <CardMeta note={note} onTagClick={onTagClick} maxTags={2} />
    </div>
  )
}

// ─── Simple ──────────────────────────────────────────────────────────────────

function SimpleCard({ note, onTagClick }: { note: Note; onTagClick?: (name: string) => void }) {
  const imageObj = note.objects.find(o => o.type === 'image')
  const textObj  = note.objects.find(o => o.type === 'text')
  const text = textObj ? getObjectDisplayText(textObj) : null

  // Только картинка — без заголовка, изображение в край
  if (imageObj && !textObj) {
    return (
      <Link
        draggable={false}
        to={notePageHref(note)}
        className={`${styles.card} ${styles.cardMedia} ${styles.cardSimpleImage}`}
        style={visualRatioStyle(imageObj, 0.82)}
      >
        <AuthImage
          className={styles.simpleImageMedia}
          src={getObjectPreviewSource(imageObj)}
          alt={note.title}
        />
        <SoftOverlay note={note} onTagClick={onTagClick} />
      </Link>
    )
  }

  if (imageObj && textObj) {
    return (
      <Link
        draggable={false}
        to={notePageHref(note)}
        className={`${styles.card} ${styles.cardMedia} ${styles.cardSimpleImage} ${styles.cardImageText} ${textDensityClass(text)}`}
        style={visualRatioStyle(imageObj, text && text.length > 220 ? 0.92 : 1.08)}
      >
        <AuthImage
          className={styles.simpleImageMedia}
          src={getObjectPreviewSource(imageObj)}
          alt={note.title}
        />
        <SoftOverlay note={note} description={text} onTagClick={onTagClick} />
      </Link>
    )
  }

  return (
    <Link
      draggable={false}
      to={notePageHref(note)}
      className={`${styles.card} ${styles.cardSimple} ${styles.cardTextOnly} ${textDensityClass(text)}`}
    >
      <div className={styles.cardTextHead}>
        <SavedDate note={note} />
        <div className={styles.title}>{note.title}</div>
      </div>
      <SearchMatchSnippet note={note} />
      {textObj && <div className={styles.excerpt}>{text}</div>}
      <CardMeta note={note} onTagClick={onTagClick} />
    </Link>
  )
}

// ─── Collection ───────────────────────────────────────────────────────────────

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
      return (
        <div className={styles.thumbPending} style={thumbStyle}>
          <LoaderSpinner size="md" />
        </div>
      )
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
          <LoaderSpinner size="md" />
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
  const textObj = note.objects.find(o => o.type === 'text')
  const description = textObj ? getObjectDisplayText(textObj) : null
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
  } else if (visualObjs.length > 2) {
    const visible = visualObjs.slice(0, 4)
    visual = (
      <div className={styles.collectionMosaic}>
        {visible.map((obj, index) => (
          <div key={obj.id} className={index === 0 ? styles.collectionMosaicMain : styles.collectionMosaicCell}>
            <LayerContent obj={obj} fallback={fallback} />
          </div>
        ))}
        {visualObjs.length > visible.length && (
          <span className={styles.collectionMoreBadge}>+{visualObjs.length - visible.length}</span>
        )}
      </div>
    )
  } else {
    visual = (
      <div className={styles.collectionSingleNonImage}>
        <LayerContent obj={undefined} fallback={fallback} />
      </div>
    )
  }

  const primaryVisual = visualObjs[0]

  return (
    <Link
      draggable={false}
      to={notePageHref(note)}
      className={`${styles.card} ${styles.cardMedia} ${styles.cardCollection}`}
      style={visualRatioStyle(primaryVisual, visualObjs.length > 2 ? 1.12 : 1.05)}
    >
      <div className={styles.collectionVisual}>
        {visual}
      </div>
      <SoftOverlay note={note} titleNode={titleNode} description={description} onTagClick={onTagClick}>
        <div className={styles.overlayMetaCluster}>
          <CollectionStats objects={note.objects} />
        </div>
      </SoftOverlay>
      {note.searchMatches?.length ? (
        <div className={styles.cardFooter}>
          <SearchMatchSnippet note={note} />
        </div>
      ) : null}
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
  const visualObject = imageObj ?? (docThumb ? firstDoc : undefined) ?? (firstLinkThumb ? firstLink : undefined)
  const text = textObj ? getObjectDisplayText(textObj) : null
  const hasAttachmentFooter = links.length > 0 || docs.length > 0
  const shouldOverlayText = Boolean(visualObject && text && !/^https?:\/\//.test(textObj?.content ?? ''))

  return (
    <Link
      draggable={false}
      to={notePageHref(note)}
      className={`${styles.card} ${styles.cardMedia} ${styles.cardComposite}`}
      style={visualRatioStyle(visualObject, textObj ? 0.92 : 1.18)}
    >

      {/* Cover */}
      <div className={styles.compositeCover}>
        {imageObj
          ? <AuthImage src={getObjectPreviewSource(imageObj)} alt="" className={styles.compositeCoverImg} />
          : docThumb
            ? <AuthImage src={docThumb} alt="" className={styles.compositeCoverImg} style={firstDoc?.imageWidth && firstDoc?.imageHeight ? { aspectRatio: `${firstDoc.imageWidth}/${firstDoc.imageHeight}` } : undefined} />
            : firstDoc?.thumbnailUrl === null
              ? (
                <div className={styles.thumbPending}>
                  <LoaderSpinner size="md" />
                </div>
              )
              : firstLink
                ? firstLinkThumb
                  ? <AuthImage src={firstLinkThumb} alt="" className={styles.compositeCoverImg} />
                  : (
                    <div className={styles.compositeCoverEmpty}>
                      <div className={styles.linkCoverInner}>
                        <div className={styles.linkFaviconRow}>
                          {links.slice(0, 4).map(l => <LinkFaviconItem key={l.id} url={l.content} />)}
                        </div>
                        {firstLink.thumbnailUrl === null && <LoaderSpinner size="md" />}
                      </div>
                    </div>
                  )
                : <div className={styles.compositeCoverEmpty}>
                    {textObj && <span className={styles.compositeCoverText}>{getObjectDisplayText(textObj, 240)}</span>}
                  </div>
        }
        <SoftOverlay
          note={note}
          titleNode={titleNode}
          description={shouldOverlayText ? text : undefined}
          onTagClick={onTagClick}
        >
        </SoftOverlay>
      </div>

      {note.searchMatches?.length ? (
        <div className={styles.cardFooter}>
          <SearchMatchSnippet note={note} />
        </div>
      ) : null}

      {hasAttachmentFooter && (
      <div className={`${styles.cardFooter} ${styles.attachmentFooter}`}>
        {links.length > 0 && (
          <div className={styles.compositeChips}>
            {links.slice(0, 2).map(o => <LinkChip key={o.id} obj={o} />)}
            {links.length > 2 && <span className={styles.moreTag}>+{links.length - 2}</span>}
          </div>
        )}

        {docs.length > 0 && (
          <div className={styles.compositeChips}>
            {docs.slice(0, 2).map(o => <DocChip key={o.id} obj={o} />)}
            {docs.length > 2 && <span className={styles.moreTag}>+{docs.length - 2}</span>}
          </div>
        )}
      </div>
      )}

      {!shouldOverlayText && textObj && text && !/^https?:\/\//.test(textObj.content) && (
        <div className={`${styles.cardFooter} ${textDensityClass(text)}`}>
          <SearchMatchSnippet note={note} />
          <div className={styles.excerpt}>{text}</div>
        </div>
      )}
    </Link>
  )
}

// ─── DnD wrapper ──────────────────────────────────────────────────────────────

const HIGHLIGHT_MS = 5000

export function NoteCard({ note, isNew, isDragging, onTagClick }: { note: Note; isNew?: boolean; isDragging?: boolean; onTagClick?: (tag: string) => void }) {
  const wrapperRef = useRef<HTMLDivElement>(null)
  const [fileHoverState, setFileHoverState] = useState<'new' | 'merge' | null>(null)

  // Rename after merge
  const [renamePending, setRenamePending] = useState(false)
  const [renameValue,   setRenameValue]   = useState('')
  const { mutate: updateNote } = useUpdateNote()

  function handleRenameSubmit() {
    const title = renameValue.trim() || note.title
    updateNote({ noteRef: note.id, data: { title } })
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

  const { mutate: upload }   = useUploadFiles()
  const { mutate: addFiles } = useAddFilesToNote()
  const { mutate: syncLocal, isPending: isSyncing } = useSyncLocalNote()
  const { pushNotice } = useUploadContext()

  // Стабильные рефы, чтобы useEffect не переподписывался на каждый рендер
  const uploadRef   = useRef(upload)
  const addFilesRef = useRef(addFiles)
  const pushNoticeRef = useRef(pushNotice)
  useEffect(() => { uploadRef.current   = upload   })
  useEffect(() => { addFilesRef.current = addFiles })
  useEffect(() => { pushNoticeRef.current = pushNotice })

  const dragEnterTimeRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    const el = wrapperRef.current
    if (!el) return

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
        const { accepted, rejected } = partitionUploadFiles(files)
        for (const r of rejected) pushNoticeRef.current(r.reason)
        if (accepted.length === 0) return
        if (elapsed < FILE_HOVER_THRESHOLD_MS) {
          uploadRef.current({ files: accepted })
        } else {
          addFilesRef.current({ noteId: note.id, files: accepted })
        }
      },
    })

    return () => {
      cleanupFileDrop()
    }
  }, [note.id])

  const cls = [
    styles.cardWrapper,
    isDragging                 ? styles.isDragging      : '',
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
  const dropRef = useRef<HTMLDivElement>(null)
  const modalDropRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const editorRef = useRef<Editor | null>(null)
  const blobNamesRef = useRef(new Map<string, string>())
  const objectUrlsRef = useRef<string[]>([])

  const [isOver, setIsOver] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [isEditorEmpty, setIsEditorEmpty] = useState(true)
  const [files, setFiles] = useState<File[]>([])
  const [slashMenu, setSlashMenu] = useState<{ visible: boolean; top: number; left: number; query: string }>({
    visible: false,
    top: 0,
    left: 0,
    query: '',
  })

  const { mutate: upload } = useUploadFiles()
  const { mutate: create } = useCreateNote()
  const { isFileDragging } = useDragContext()
  const { pushNotice } = useUploadContext()

  const attachFiles = useCallback((incoming: File[], insertImages: boolean) => {
    if (incoming.length === 0) return
    const { accepted, rejected } = partitionUploadFiles(incoming)
    for (const r of rejected) pushNotice(r.reason)
    if (accepted.length === 0) return
    setFiles(prev => [...prev, ...accepted])

    if (!insertImages) return
    const editor = editorRef.current
    if (!editor) return

    accepted
      .filter(file => file.type.startsWith('image/'))
      .forEach((file, index) => {
        const name = file.name || `pasted-image-${Date.now()}-${index + 1}.png`
        const url = URL.createObjectURL(file)
        objectUrlsRef.current.push(url)
        blobNamesRef.current.set(url, name)
        editor.chain().focus().setImage({ src: url, alt: name, title: name }).run()
      })
  }, [])

  const updateSlashMenu = useCallback((editor: Editor) => {
    const { selection } = editor.state
    if (!selection.empty) {
      setSlashMenu(prev => prev.visible ? { ...prev, visible: false } : prev)
      return
    }

    const $from = selection.$from
    const textBeforeCursor = $from.parent.textBetween(0, $from.parentOffset, '\n', '\n')
    const match = /^\/([\p{L}\p{N}_-]*)?$/u.exec(textBeforeCursor)
    const root = modalDropRef.current ?? dropRef.current
    if (!match || !root) {
      setSlashMenu(prev => prev.visible ? { ...prev, visible: false } : prev)
      return
    }

    const coords = editor.view.coordsAtPos(selection.from)
    const bounds = root.getBoundingClientRect()
    setSlashMenu({
      visible: true,
      top: coords.bottom - bounds.top + 8,
      left: Math.max(16, coords.left - bounds.left),
      query: match[1]?.toLowerCase() ?? '',
    })
  }, [])

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3] },
        link: false,
      }),
      UnderlineExtension,
      Typography,
      LinkExtension.configure({
        autolink: true,
        openOnClick: false,
        linkOnPaste: true,
        HTMLAttributes: { rel: 'noopener noreferrer nofollow' },
      }),
      Image.configure({
        allowBase64: true,
        inline: false,
      }),
      TaskList,
      TaskItem.configure({ nested: true }),
      Placeholder.configure({
        placeholder: 'Введите / для команд или вставьте текст из Word',
      }),
    ],
    autofocus: false,
    content: '',
    immediatelyRender: false,
    editorProps: {
      attributes: {
        class: styles.quickNoteEditorContent,
      },
      handlePaste: (_view, event) => {
        const items = Array.from(event.clipboardData?.items ?? [])
        const pastedImages = items
          .filter(item => item.kind === 'file' && item.type.startsWith('image/'))
          .map((item, index) => {
            const file = item.getAsFile()
            if (!file) return null
            const ext = file.type.split('/')[1] || 'png'
            return new File([file], file.name || `pasted-image-${Date.now()}-${index + 1}.${ext}`, { type: file.type })
          })
          .filter((file): file is File => Boolean(file))

        if (pastedImages.length === 0) return false
        event.preventDefault()
        attachFiles(pastedImages, true)
        return true
      },
      handleKeyDown: (_view, event) => {
        if (event.key === 'Escape') {
          handleCancel()
          return true
        }
        if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
          handleSubmit()
          return true
        }
        if (event.key === 'Enter' && slashMenu.visible && slashItems.length > 0) {
          runSlashCommand(slashItems[0].id)
          return true
        }
        return false
      },
    },
    onUpdate: ({ editor }) => {
      setIsEditorEmpty(editor.isEmpty)
      updateSlashMenu(editor)
    },
    onSelectionUpdate: ({ editor }) => updateSlashMenu(editor),
  })

  useEffect(() => {
    editorRef.current = editor
  }, [editor])

  useEffect(() => () => {
    objectUrlsRef.current.forEach(url => URL.revokeObjectURL(url))
  }, [])

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
        const dropped = getFiles({ source })
        if (dropped.length === 0) return
        const { accepted, rejected } = partitionUploadFiles(dropped)
        for (const r of rejected) pushNotice(r.reason)
        if (accepted.length === 0) return
        upload({ files: accepted })
      },
    })
  }, [upload, pushNotice])

  useEffect(() => {
    if (!isEditing) return
    const el = modalDropRef.current
    if (!el) return
    return dropTargetForExternal({
      element: el,
      canDrop: containsFiles,
      onDragEnter: () => setIsOver(true),
      onDragLeave: () => setIsOver(false),
      onDrop: ({ source }) => {
        setIsOver(false)
        const dropped = getFiles({ source })
        if (dropped.length > 0) attachFiles(dropped, true)
      },
    })
  }, [attachFiles, isEditing])

  function handleOpen() {
    setIsEditing(true)
    onClick?.()
    window.setTimeout(() => editorRef.current?.commands.focus('end'), 0)
  }

  function handleCancel() {
    setIsEditing(false)
    editorRef.current?.commands.clearContent()
    setIsEditorEmpty(true)
    setSlashMenu(prev => ({ ...prev, visible: false }))
    setFiles([])
    blobNamesRef.current.clear()
    objectUrlsRef.current.forEach(url => URL.revokeObjectURL(url))
    objectUrlsRef.current = []
  }

  function handleSubmit() {
    const html = editorRef.current?.getHTML() ?? ''
    const markdown = replaceBlobImageSources(htmlToMarkdown(html), blobNamesRef.current).trim()
    const hasFiles = files.length > 0

    if (!markdown && !hasFiles) { handleCancel(); return }

    if (hasFiles) {
      upload({ files, text: markdown || undefined })
    } else {
      const title = makeMarkdownTitle(markdown)
      create({
        title,
        type: 'simple',
        objects: [{ id: `txt-${Date.now()}`, type: 'text', content: markdown, createdAt: new Date().toISOString() }],
      })
    }
    handleCancel()
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(e.target.files ?? [])
    attachFiles(picked, true)
    e.target.value = ''
  }

  function removeFile(idx: number) {
    setFiles(prev => prev.filter((_, i) => i !== idx))
  }

  function clearSlashTrigger() {
    const editor = editorRef.current
    if (!editor) return
    const { selection } = editor.state
    const from = selection.from
    const start = from - selection.$from.parentOffset
    editor.chain().focus().deleteRange({ from: start, to: from }).run()
  }

  function runSlashCommand(command: string) {
    const editor = editorRef.current
    if (!editor) return
    clearSlashTrigger()
    const chain = editor.chain().focus()
    if (command === 'heading') chain.toggleHeading({ level: 1 }).run()
    if (command === 'task') chain.toggleTaskList().run()
    if (command === 'image') fileInputRef.current?.click()
    if (command === 'divider') chain.setHorizontalRule().run()
    if (command === 'quote') chain.toggleBlockquote().run()
    if (command === 'code') chain.toggleCodeBlock().run()
    if (command === 'bullet') chain.toggleBulletList().run()
    if (command === 'ordered') chain.toggleOrderedList().run()
    setSlashMenu(prev => ({ ...prev, visible: false }))
  }

  function setLink() {
    const editor = editorRef.current
    if (!editor) return
    const previousUrl = editor.getAttributes('link').href as string | undefined
    const url = window.prompt('Ссылка', previousUrl ?? 'https://')
    if (url === null) return
    if (!url.trim()) {
      editor.chain().focus().extendMarkRange('link').unsetLink().run()
      return
    }
    editor.chain().focus().extendMarkRange('link').setLink({ href: url.trim() }).run()
  }

  const showFileMode = (isFileDragging || isOver) && !isEditing

  const wrapperCls = [
    styles.addCard,
    isOver && !isEditing         ? styles.addCardOver      : '',
    isFileDragging && !isEditing ? styles.addCardFileDrag  : '',
  ].filter(Boolean).join(' ')

  const slashItems = [
    { id: 'heading', label: 'Заголовок', icon: <Heading1 size={18} />, keywords: 'heading заголовок h1' },
    { id: 'task', label: 'Список задач', icon: <ListChecks size={18} />, keywords: 'task todo задача чеклист' },
    { id: 'image', label: 'Изображение', icon: <ImageIcon size={18} />, keywords: 'image img фото картинка' },
    { id: 'divider', label: 'Разделитель', icon: <Minus size={18} />, keywords: 'divider hr линия' },
    { id: 'quote', label: 'Цитата', icon: <TextQuote size={18} />, keywords: 'quote цитата' },
    { id: 'code', label: 'Код', icon: <Code2 size={18} />, keywords: 'code код' },
    { id: 'bullet', label: 'Маркированный список', icon: <List size={18} />, keywords: 'bullet list список' },
    { id: 'ordered', label: 'Нумерованный список', icon: <ListOrdered size={18} />, keywords: 'ordered number список' },
  ].filter(item => !slashMenu.query || item.keywords.includes(slashMenu.query) || item.label.toLowerCase().includes(slashMenu.query))

  const editorDialog = isEditing && typeof document !== 'undefined' ? createPortal(
    <>
      <div className={styles.addCardBackdrop} onClick={handleCancel} />
      <div ref={modalDropRef} className={`${styles.addCard} ${styles.addCardEditing}`}>
        <>
          <div className={styles.addCardEditorShell}>
            <div className={styles.addCardKicker}>Новая заметка</div>
            {editor && (
              <BubbleMenu editor={editor} className={styles.quickNoteBubble}>
                <button type="button" className={editor.isActive('bold') ? styles.quickNoteToolActive : ''} onMouseDown={e => { e.preventDefault(); editor.chain().focus().toggleBold().run() }} title="Жирный">
                  <Bold size={18} />
                </button>
                <button type="button" className={editor.isActive('italic') ? styles.quickNoteToolActive : ''} onMouseDown={e => { e.preventDefault(); editor.chain().focus().toggleItalic().run() }} title="Курсив">
                  <Italic size={18} />
                </button>
                <button type="button" className={editor.isActive('underline') ? styles.quickNoteToolActive : ''} onMouseDown={e => { e.preventDefault(); editor.chain().focus().toggleUnderline().run() }} title="Подчеркнуть">
                  <Underline size={18} />
                </button>
                <button type="button" className={editor.isActive('link') ? styles.quickNoteToolActive : ''} onMouseDown={e => { e.preventDefault(); setLink() }} title="Ссылка">
                  <Link2 size={18} />
                </button>
                <button type="button" className={editor.isActive('code') ? styles.quickNoteToolActive : ''} onMouseDown={e => { e.preventDefault(); editor.chain().focus().toggleCode().run() }} title="Код">
                  <Code2 size={18} />
                </button>
              </BubbleMenu>
            )}
            <EditorContent editor={editor} className={styles.quickNoteEditor} />
            {slashMenu.visible && slashItems.length > 0 && (
              <div className={styles.quickNoteSlashMenu} style={{ top: slashMenu.top, left: slashMenu.left }}>
                {slashItems.map(item => (
                  <button key={item.id} type="button" onMouseDown={e => { e.preventDefault(); runSlashCommand(item.id) }}>
                    {item.icon}
                    <span>{item.label}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
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
              <Paperclip size={15} />
              <input ref={fileInputRef} type="file" multiple hidden onChange={handleFileChange} />
            </label>
            <button className={styles.addCardCancelBtn} onClick={handleCancel}>Отмена</button>
            <button className={styles.addCardSubmitBtn} disabled={isEditorEmpty && files.length === 0} onClick={handleSubmit}>Создать</button>
          </div>
        </>
      </div>
    </>,
    document.body,
  ) : null

  return (
    <>
      <div ref={dropRef} className={wrapperCls}>
        <button className={styles.addCardTrigger} onClick={handleOpen}>
          {showFileMode
            ? <UploadCloud size={28} className={styles.addIcon} />
            : <Plus size={18} className={styles.addIcon} />
          }
          <span className={styles.addCardTriggerText}>
            <strong>{isOver ? 'Отпустите файлы' : showFileMode ? 'Бросьте сюда' : 'Новая заметка'}</strong>
            <span>{showFileMode ? 'Создать из файлов' : 'Markdown, вставка из Word, / команды'}</span>
          </span>
        </button>
      </div>
      {editorDialog}
    </>
  )
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────

export function SkeletonCard() {
  return <div className={styles.skeletonCard} />
}
