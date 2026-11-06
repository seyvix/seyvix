import { CalendarDays, Clock3, ExternalLink, Layers3, Send } from 'lucide-react'
import type { Note, NoteObject } from '../../types'
import { ObjectKindIcon } from './DetailParts'
import {
  formatDetailDate,
  noteTypeLabel,
  objectCountSummary,
  objectDomId,
  objectKindLabel,
  objectNavTitle,
  primarySource,
  sourceOriginLabel,
} from './format'
import styles from './Sidebar.module.css'

/** Sidebar summary: dates, source, per-type counts and an in-page table of contents. */
export function NoteOverview({ note, objects }: { note: Note; objects: NoteObject[] }) {
  const source = primarySource(note, objects)
  const sourceDate = formatDetailDate(source?.originalCreatedAt)
  const counts = objectCountSummary(objects)
  const origin = source ? sourceOriginLabel(source) : null

  return (
    <div className={styles.overviewPanel}>
      <div className={styles.overviewHeader}>
        <span>{noteTypeLabel(note.type)}</span>
        <strong>{objects.length}</strong>
      </div>

      <div className={styles.overviewFacts}>
        <div className={styles.overviewFact}>
          <CalendarDays size={14} />
          <div>
            <span>Создано</span>
            <strong>{formatDetailDate(note.createdAt) ?? 'нет даты'}</strong>
          </div>
        </div>
        <div className={styles.overviewFact}>
          <Clock3 size={14} />
          <div>
            <span>Изменено</span>
            <strong>{formatDetailDate(note.updatedAt) ?? 'нет даты'}</strong>
          </div>
        </div>
        {source && (
          <div className={styles.overviewFact}>
            <Send size={14} />
            <div>
              <span>{source.providerLabel}</span>
              {source.url ? (
                <a href={source.url} target="_blank" rel="noreferrer">
                  {origin ?? source.url}
                  <ExternalLink size={11} />
                </a>
              ) : (
                <strong>{origin ?? 'Источник'}</strong>
              )}
              {sourceDate && <small>{sourceDate}</small>}
            </div>
          </div>
        )}
      </div>

      {counts.length > 0 && (
        <div className={styles.objectCounts}>
          {counts.map(item => (
            <span key={item.type} title={objectKindLabel(item.type)}>
              <ObjectKindIcon type={item.type} />
              {item.count}
            </span>
          ))}
        </div>
      )}

      {objects.length > 1 && (
        <nav className={styles.objectNav} aria-label="Содержимое заметки">
          <div className={styles.objectNavTitle}>
            <Layers3 size={14} />
            <span>Содержимое</span>
          </div>
          {objects.map((obj, index) => (
            <a key={obj.id} href={`#${objectDomId(obj.id)}`}>
              <ObjectKindIcon type={obj.type} />
              <span>{objectNavTitle(obj, index)}</span>
            </a>
          ))}
        </nav>
      )}
    </div>
  )
}
