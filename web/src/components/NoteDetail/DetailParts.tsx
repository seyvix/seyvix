import { ExternalLink, File, Globe, Image as ImageIcon, Link2, Mic2, Send, Type, Video } from 'lucide-react'
import type { NoteObject, SourceMetadata, Tag } from '../../types'
import type { NoteDetailSourceModel } from '../../utils/noteCardPresentation'
import { getTagColor } from '../../utils/tagColor'
import { formatDetailDate, sourceOriginLabel } from './format'
import styles from './NoteDetail.module.css'

const OBJECT_KIND_ICON: Record<NoteObject['type'], typeof Type> = {
  text: Type,
  image: ImageIcon,
  link: Link2,
  document: File,
  audio: Mic2,
  video: Video,
}

export function ObjectKindIcon({ type, size = 14 }: { type: NoteObject['type']; size?: number }) {
  const Icon = OBJECT_KIND_ICON[type]
  return <Icon size={size} />
}

export function TagChips({ tags }: { tags: Tag[] }) {
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

export function ObjectSourceInline({ source }: { source?: SourceMetadata | null }) {
  if (!source) return null
  const origin = sourceOriginLabel(source)
  const content = (
    <>
      <Send size={12} />
      <span>{origin ? `${source.providerLabel} · ${origin}` : source.providerLabel}</span>
      {source.url && <ExternalLink size={11} />}
    </>
  )
  return source.url
    ? <a className={styles.objectChromeSource} href={source.url} target="_blank" rel="noreferrer">{content}</a>
    : <span className={styles.objectChromeSource}>{content}</span>
}

export function DetailSourcePanel({ source }: { source: NoteDetailSourceModel }) {
  const sourceDate = formatDetailDate(source.originalCreatedAt)
  const Icon = source.provider === 'telegram' ? Send : Globe
  return (
    <section className={styles.detailSourcePanel}>
      <div className={styles.detailSourceIcon}>
        <Icon size={16} />
      </div>
      <div className={styles.detailSourceBody}>
        <span>{source.providerLabel}</span>
        <strong>{source.originLabel ?? source.providerLabel}</strong>
        {sourceDate && <small>{sourceDate}</small>}
      </div>
      {source.href && (
        <a className={styles.detailSourceAction} href={source.href} target="_blank" rel="noreferrer" title="Открыть оригинал">
          <ExternalLink size={14} />
        </a>
      )}
    </section>
  )
}
