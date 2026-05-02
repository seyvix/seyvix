import { useRef } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import type { Note } from '../../types'
import { NoteCard, AddNoteCard } from '../NoteCard/NoteCard'
import { DragProvider } from '../../contexts/DragContext'
import { useSettings } from '../../contexts/SettingsContext'
import styles from './NoteGrid.module.css'

interface NoteGridProps {
  notes: Note[]
  onAddNote?: () => void
  onTagClick?: (tag: string) => void
}

export function NoteGrid({ notes, onAddNote, onTagClick }: NoteGridProps) {
  const columnMapRef  = useRef(new Map<string, number>())
  const counterRef    = useRef(0)
  const knownKeysRef  = useRef(new Set<string>())
  const isFirstRender = useRef(true)
  const prevColsRef   = useRef<number | null>(null)

  const { cols: COLS } = useSettings()

  if (prevColsRef.current !== null && prevColsRef.current !== COLS) {
    columnMapRef.current = new Map()
    counterRef.current = 0
  }
  prevColsRef.current = COLS

  if (isFirstRender.current) {
    isFirstRender.current = false
    notes.forEach(n => knownKeysRef.current.add(n.stableKey ?? n.id))
  }

  // Assign columns. stableKey is the permanent identity — survives tempId→serverId.
  notes.forEach(note => {
    const key = note.stableKey ?? note.id
    if (!columnMapRef.current.has(key)) {
      columnMapRef.current.set(key, counterRef.current % COLS)
      counterRef.current++
    }
  })

  const columns: Note[][] = Array.from({ length: COLS }, () => [])
  notes.forEach(note => {
    const key = note.stableKey ?? note.id
    const colIdx = columnMapRef.current.get(key) ?? 0
    columns[colIdx].push(note)
  })

  const STAGGER = [0, 24, 12, 18, 8]

  return (
    <DragProvider>
      <div className={styles.grid}>
        {columns.map((col, colIdx) => (
          <div key={colIdx} className={styles.column} style={{ marginTop: STAGGER[colIdx] ?? 0 }}>
            {colIdx === 0 && <AddNoteCard onClick={onAddNote} />}

            <AnimatePresence initial={false}>
              {col.map(note => {
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
                    transition={{ duration: 0.28, ease: [0.25, 0.46, 0.45, 0.94] }}
                  >
                    <NoteCard note={note} isNew={isNew} onTagClick={onTagClick} />
                  </motion.div>
                )
              })}
            </AnimatePresence>
          </div>
        ))}
      </div>
    </DragProvider>
  )
}
