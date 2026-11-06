import { memo, useMemo, type ReactNode } from 'react'
import { AlignLeft, ExternalLink, FileText, ImageIcon, Link2, Send, Video, Volume2 } from 'lucide-react'
import AuthImage from '../AuthImage/AuthImage'
import { InlineMarkdown } from '../Markdown/InlineMarkdown'
import type { Note, NoteObject, Tag } from '../../types'
import { useFavicon } from '../../hooks/useFavicon'
import { getTagColor } from '../../utils/tagColor'
import { normalizedHighlightRanges } from '../../utils/searchHighlight'
import {
  collectLinkChips,
  collectSourceChips,
  getNoteDisplayTitle,
  getSavedDateLabel,
  type LinkChipModel,
} from '../../utils/noteCardPresentation'
import { documentThumb, fileExtension, type TextDensity } from './cardModel'
import styles from './NoteCard.module.css'

export type TagClickHandler = (name: string) => void

const DENSITY_CLASS: Record<TextDensity, string> = {
  short: styles.cardTextShort,
  medium: styles.cardTextMedium,
  long: styles.cardTextLong,
}

export function densityClassName(density: TextDensity): string {
  return DENSITY_CLASS[density]
}

// ─── Chips ────────────────────────────────────────────────────────────────────

function TagList({ tags, onTagClick, max }: { tags: Tag[]; onTagClick?: TagClickHandler; max: number }) {
  const visibleTags = tags.slice(0, max)
  const hiddenCount = tags.length - visibleTags.length
  return (
    <>
      {visibleTags.map(tag => {
        const { bg, text } = getTagColor(tag.name)
        return (
          <span
            key={tag.id}
            className={styles.tag}
            style={{ background: bg, color: text }}
            onClick={event => {
              event.preventDefault()
              event.stopPropagation()
              onTagClick?.(tag.name)
            }}
          >
            {tag.name}
          </span>
        )
      })}
      {hiddenCount > 0 && <span className={styles.moreTag}>+{hiddenCount}</span>}
    </>
  )
}

function LinkChip({ chip }: { chip: LinkChipModel }) {
  const favicon = useFavicon(chip.url)
  return (
    <span className={styles.linkChip} title={chip.title}>
      <div className={styles.linkChipIcon}>
        {favicon ? <img src={favicon} alt="" className={styles.linkChipFavicon} /> : <ExternalLink size={12} />}
      </div>
      <span className={styles.linkChipDomain}>{chip.label}</span>
      <ExternalLink size={9} className={styles.linkChipArrow} />
    </span>
  )
}

/** Source, tag and link chips under a card. */
export function CardMeta({ note, onTagClick, maxTags = 4 }: { note: Note; onTagClick?: TagClickHandler; maxTags?: number }) {
  const sourceChips = useMemo(() => collectSourceChips(note), [note])
  const linkChips = useMemo(() => collectLinkChips(note), [note])
  if (sourceChips.length === 0 && note.tags.length === 0 && linkChips.length === 0) return null
  return (
    <div className={styles.tags}>
      {sourceChips.map(chip => (
        <span key={chip.key} className={styles.sourceTag} title={chip.title}>
          <Send size={10} />
          <span className={styles.sourceProvider}>{chip.providerLabel}</span>
          {chip.originLabel && <span className={styles.sourceOrigin}>{chip.originLabel}</span>}
        </span>
      ))}
      <TagList tags={note.tags} onTagClick={onTagClick} max={maxTags} />
      {linkChips.map(chip => <LinkChip key={chip.key} chip={chip} />)}
    </div>
  )
}

export function DocChip({ obj }: { obj: NoteObject }) {
  const label = obj.filename ?? obj.content
  const thumb = documentThumb(obj)
  return (
    <div className={styles.docChip}>
      {thumb
        ? <AuthImage src={thumb} alt="" className={styles.docChipCover} />
        : <div className={styles.docChipIconWrap}><FileText size={13} /></div>}
      <span className={styles.docChipName}>{label.replace(/\.[^.]+$/, '')}</span>
      <span className={styles.docChipExt}>{fileExtension(label)}</span>
    </div>
  )
}

// ─── Text ─────────────────────────────────────────────────────────────────────

export const SavedDate = memo(function SavedDate({ createdAt, overlay = false }: { createdAt: string; overlay?: boolean }) {
  const label = useMemo(() => getSavedDateLabel(createdAt), [createdAt])
  if (!label) return null
  return <span className={overlay ? `${styles.savedDate} ${styles.savedDateOverlay}` : styles.savedDate}>{label}</span>
})

export function SearchMatchSnippet({ note }: { note: Note }) {
  const match = note.searchMatches?.[0]
  if (!match?.text) return null
  const parts: ReactNode[] = []
  let cursor = 0
  for (const range of normalizedHighlightRanges(match).slice(0, 6)) {
    if (range.start > cursor) parts.push(match.text.slice(cursor, range.start))
    parts.push(<mark key={`${range.start}-${range.end}`}>{match.text.slice(range.start, range.end)}</mark>)
    cursor = range.end
  }
  if (cursor < match.text.length) parts.push(match.text.slice(cursor))
  return <div className={styles.searchSnippet}>{parts}</div>
}

export function CardTitle({ title }: { title: string | null }) {
  return title ? <div className={styles.title}>{title}</div> : null
}

/** Gradient overlay at the bottom of visual cards: date, title, excerpt, chips. */
export function SoftOverlay({
  note,
  title,
  description,
  children,
  onTagClick,
}: {
  note: Note
  /** `undefined` → derive from the note; `null` → no title. */
  title?: string | null
  description?: { text: string; source?: NoteObject['source'] } | null
  children?: ReactNode
  onTagClick?: TagClickHandler
}) {
  const resolvedTitle = title === undefined ? getNoteDisplayTitle(note) : title
  return (
    <div className={styles.softOverlay}>
      <div className={styles.softOverlayTop}>
        <SavedDate createdAt={note.createdAt} overlay />
        {children}
      </div>
      <CardTitle title={resolvedTitle} />
      {description && (
        <div className={styles.overlayExcerpt}>
          <InlineMarkdown text={description.text} source={description.source} />
        </div>
      )}
      <CardMeta note={note} onTagClick={onTagClick} maxTags={2} />
    </div>
  )
}

// ─── Media ────────────────────────────────────────────────────────────────────

export function MediaPlaceholder({
  type,
  className,
  label,
}: {
  type: 'audio' | 'video' | 'document'
  className?: string
  label?: string | null
}) {
  const Icon = type === 'audio' ? Volume2 : type === 'video' ? Video : FileText
  const tone = type === 'audio' ? styles.audioPlaceholder : type === 'video' ? styles.videoPlaceholder : styles.filePlaceholder
  return (
    <div className={[styles.mediaPlaceholder, tone, className].filter(Boolean).join(' ')}>
      <Icon size={type === 'audio' ? 30 : 32} />
      {label && <span>{label}</span>}
    </div>
  )
}

export function LinkFavicon({ url }: { url: string }) {
  const favicon = useFavicon(url)
  if (favicon) return <img src={favicon} alt="" className={styles.collectionLayerFavicon} />
  return <div className={styles.linkFaviconPlaceholder}><ExternalLink size={12} /></div>
}

const OBJECT_TYPE_ORDER: NoteObject['type'][] = ['image', 'video', 'audio', 'document', 'link', 'text']

const OBJECT_TYPE_ICON: Record<NoteObject['type'], ReactNode> = {
  image: <ImageIcon size={11} />,
  video: <Video size={11} />,
  audio: <Volume2 size={11} />,
  document: <FileText size={11} />,
  link: <Link2 size={11} />,
  text: <AlignLeft size={11} />,
}

export function CollectionStats({ objects }: { objects: NoteObject[] }) {
  const counts = new Map<NoteObject['type'], number>()
  for (const obj of objects) counts.set(obj.type, (counts.get(obj.type) ?? 0) + 1)
  return (
    <div className={styles.collectionStats}>
      {OBJECT_TYPE_ORDER.filter(type => counts.has(type)).map(type => (
        <span key={type} className={styles.collectionStat}>
          {OBJECT_TYPE_ICON[type]}
          {counts.get(type)}
        </span>
      ))}
    </div>
  )
}
