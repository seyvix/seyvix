import { useRef } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import type { Note } from '../../types'
import { NoteCard, AddNoteCard, SkeletonCard } from '../NoteCard/NoteCard'
import { DragProvider } from '../../contexts/DragContext'
import styles from './NoteGrid.module.css'

const COLS = 4

interface NoteGridProps {
  notes: Note[]
  onAddNote?: () => void
  isUploading?: boolean
}

export function NoteGrid({ notes, onAddNote, isUploading }: NoteGridProps) {
  // Стабильное назначение колонок по note.id
  const columnMapRef = useRef(new Map<string, number>())
  const counterRef   = useRef(0)

  // Отслеживаем id, которые уже были при предыдущем рендере —
  // они не анимируются при первой загрузке, только новые всплывают снизу
  const knownIdsRef  = useRef(new Set<string>())
  const isFirstRender = useRef(true)

  // На первом рендере заносим все id как «известные» без анимации
  if (isFirstRender.current) {
    isFirstRender.current = false
    notes.forEach(n => knownIdsRef.current.add(n.id))
  }

  notes.forEach(note => {
    if (!columnMapRef.current.has(note.id)) {
      columnMapRef.current.set(note.id, (counterRef.current + 1) % COLS)
      counterRef.current++
    }
  })

  const columns: Note[][] = Array.from({ length: COLS }, () => [])
  notes.forEach(note => {
    const colIdx = columnMapRef.current.get(note.id) ?? 0
    columns[colIdx].push(note)
  })

  return (
    <DragProvider>
      <div className={styles.grid}>
        {columns.map((col, colIdx) => (
          <div key={colIdx} className={styles.column}>
            {colIdx === 0 && <AddNoteCard onClick={onAddNote} />}
            {colIdx === 0 && isUploading && (
              <motion.div
                key="skeleton"
                initial={{ opacity: 0, y: 32 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, transition: { duration: 0.15 } }}
                transition={{ duration: 0.25 }}
              >
                <SkeletonCard />
              </motion.div>
            )}
            <AnimatePresence initial={false}>
              {col.map(note => {
                const isNew = !knownIdsRef.current.has(note.id)
                // Помечаем как известную сразу, чтобы повторный ре-рендер не анимировал
                knownIdsRef.current.add(note.id)
                return (
                  <motion.div
                    key={note.id}
                    layout
                    initial={isNew ? { opacity: 0, y: 32 } : false}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.85, transition: { duration: 0.18 } }}
                    transition={{ duration: 0.28, ease: [0.25, 0.46, 0.45, 0.94] }}
                  >
                    <NoteCard note={note} isNew={isNew} />
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
