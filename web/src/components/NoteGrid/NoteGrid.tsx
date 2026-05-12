import { useRef } from 'react'
import type { CSSProperties } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import type { Note } from '../../types'
import { NoteCard, AddNoteCard } from '../NoteCard/NoteCard'
import { DragProvider } from '../../contexts/DragContext'
import { useSettings } from '../../contexts/SettingsContext'
import type { DropPlacement } from '../../utils/reorderNotes'
import styles from './NoteGrid.module.css'

interface NoteGridProps {
  notes: Note[]
  onAddNote?: () => void
  onTagClick?: (tag: string) => void
  onMoveNote?: (sourceSlug: string, targetSlug: string, placement: DropPlacement) => void
}

export function NoteGrid({ notes, onAddNote, onTagClick, onMoveNote }: NoteGridProps) {
  const knownKeysRef = useRef(new Set<string>())
  const { cols: COLS } = useSettings()
  const tracks = COLS * 4

  return (
    <DragProvider>
      <div className={styles.grid} style={{ '--note-grid-tracks': tracks } as CSSProperties}>
        <motion.div layout="position" className={`${styles.gridItem} ${styles.gridItemCompact} ${styles.gridItemWide}`}>
          <AddNoteCard onClick={onAddNote} />
        </motion.div>

        <AnimatePresence initial={false}>
          {notes.map(note => {
            const key = note.stableKey ?? note.id
            const isNew = !knownKeysRef.current.has(key)
            knownKeysRef.current.add(key)

            return (
              <motion.div
                key={key}
                className={gridItemClass(note)}
                layout="position"
                initial={isNew ? { opacity: 0, y: 32 } : false}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.85, transition: { duration: 0.18 } }}
                transition={{ duration: 0.22, ease: [0.25, 0.46, 0.45, 0.94] }}
              >
                <NoteCard
                  note={note}
                  isNew={isNew}
                  onTagClick={onTagClick}
                  onMoveNote={onMoveNote}
                  isReorderEnabled={Boolean(onMoveNote)}
                />
              </motion.div>
            )
          })}
        </AnimatePresence>
      </div>
    </DragProvider>
  )
}

function gridItemClass(note: Note): string {
  const classes = [styles.gridItem]
  const image = note.objects.find(obj => obj.type === 'image')
  const text = note.objects.find(obj => obj.type === 'text')
  const mediaCount = note.objects.filter(obj => obj.type === 'image' || obj.type === 'video').length
  const documentCount = note.objects.filter(obj => obj.type === 'document').length
  const contentLength = `${note.title} ${text?.content ?? ''}`.length

  if (note.type === 'collection') {
    classes.push(styles.gridItemTall)
    if (note.objects.length >= 4 || mediaCount >= 2) classes.push(styles.gridItemWide)
    return classes.join(' ')
  }

  if (note.type === 'composite') {
    classes.push(documentCount > 1 || mediaCount > 1 || contentLength > 420 ? styles.gridItemWide : styles.gridItemTall)
    if (contentLength > 720) classes.push(styles.gridItemTall)
    return classes.join(' ')
  }

  if (image && !text) {
    const ratio = image.imageWidth && image.imageHeight ? image.imageWidth / image.imageHeight : 1
    if (ratio >= 1.35) classes.push(styles.gridItemWide, styles.gridItemMedium)
    else if (ratio <= 0.78) classes.push(styles.gridItemTall)
    else classes.push(styles.gridItemMedium)
    return classes.join(' ')
  }

  if (contentLength > 520) classes.push(styles.gridItemWide, styles.gridItemMedium)
  else if (contentLength < 180) classes.push(styles.gridItemCompact)
  else classes.push(styles.gridItemMedium)

  return classes.join(' ')
}
