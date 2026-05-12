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

  return (
    <DragProvider>
      <div className={styles.grid} style={{ '--note-grid-cols': COLS } as CSSProperties}>
        <AddNoteCard onClick={onAddNote} />

        <AnimatePresence initial={false}>
          {notes.map(note => {
            const key = note.stableKey ?? note.id
            const isNew = !knownKeysRef.current.has(key)
            knownKeysRef.current.add(key)

            return (
              <motion.div
                key={key}
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
