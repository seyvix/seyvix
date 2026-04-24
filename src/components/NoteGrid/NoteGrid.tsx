import { useRef } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import type { Note } from '../../types'
import { NoteCard, AddNoteCard, SkeletonCard } from '../NoteCard/NoteCard'
import { DragProvider } from '../../contexts/DragContext'
import { useUploadContext } from '../../contexts/UploadContext'
import { useSettings } from '../../contexts/SettingsContext'
import styles from './NoteGrid.module.css'

// Один слот — либо скелетон, либо карточка. Ключ (noteId) не меняется,
// поэтому React не пересоздаёт элемент — меняется только содержимое.
function NoteSlot({ note, onTagClick }: { note?: Note; onTagClick?: (tag: string) => void }) {
  return (
    <AnimatePresence mode="popLayout" initial={false}>
      {note
        ? <motion.div
            key="note"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.25 }}
          >
            <NoteCard note={note} onTagClick={onTagClick} />
          </motion.div>
        : <motion.div
            key="skeleton"
            exit={{ opacity: 0, transition: { duration: 0.15 } }}
          >
            <SkeletonCard />
          </motion.div>
      }
    </AnimatePresence>
  )
}

interface NoteGridProps {
  notes: Note[]
  onAddNote?: () => void
  onTagClick?: (tag: string) => void
}

export function NoteGrid({ notes, onAddNote, onTagClick }: NoteGridProps) {
  const columnMapRef  = useRef(new Map<string, number>())
  const counterRef    = useRef(0)
  const knownIdsRef   = useRef(new Set<string>())
  const isFirstRender = useRef(true)
  const prevColsRef   = useRef<number | null>(null)

  const { jobs } = useUploadContext()
  const { cols: COLS } = useSettings()

  if (prevColsRef.current !== null && prevColsRef.current !== COLS) {
    columnMapRef.current = new Map()
    counterRef.current = 0
  }
  prevColsRef.current = COLS

  if (isFirstRender.current) {
    isFirstRender.current = false
    notes.forEach(n => knownIdsRef.current.add(n.id))
  }

  // Резервируем колонку под каждый активный джоб по noteId
  jobs.forEach(({ noteId }) => {
    if (!columnMapRef.current.has(noteId)) {
      columnMapRef.current.set(noteId, (counterRef.current + 1) % COLS)
      counterRef.current++
    }
    // Помечаем noteId как «известный», чтобы при появлении не анимировался отдельно
    knownIdsRef.current.add(noteId)
  })

  // Назначаем колонки нотам, которых ещё нет в карте
  notes.forEach(note => {
    if (!columnMapRef.current.has(note.id)) {
      columnMapRef.current.set(note.id, (counterRef.current + 1) % COLS)
      counterRef.current++
    }
  })

  // Ноты, принадлежащие активному джобу — рендерятся через NoteSlot
  const jobNoteIds = new Set(jobs.map(j => j.noteId))

  const columns: Note[][] = Array.from({ length: COLS }, () => [])
  notes
    .filter(note => !jobNoteIds.has(note.id))  // обычные ноты — без джоба
    .forEach(note => {
      const colIdx = columnMapRef.current.get(note.id) ?? 0
      columns[colIdx].push(note)
    })

  const STAGGER = [0, 24, 12, 18, 8]

  return (
    <DragProvider>
      <div className={styles.grid}>
        {columns.map((col, colIdx) => {
          // Джоб-слоты для этой колонки: pending (нота не пришла) или arrived (нота уже здесь)
          const jobSlots = jobs
            .filter(j => columnMapRef.current.get(j.noteId) === colIdx)
            .map(j => ({ noteId: j.noteId, jobId: j.jobId, note: notes.find(n => n.id === j.noteId) }))

          return (
            <div key={colIdx} className={styles.column} style={{ marginTop: STAGGER[colIdx] ?? 0 }}>
              {colIdx === 0 && <AddNoteCard onClick={onAddNote} />}

              <AnimatePresence initial={false}>
                {/* Джоб-слоты: skeleton → note без пересоздания элемента */}
                {jobSlots.map(({ noteId, jobId, note }) => (
                  <motion.div
                    key={noteId}
                    layout
                    initial={{ opacity: 0, y: 32 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.85, transition: { duration: 0.18 } }}
                    transition={{ duration: 0.28, ease: [0.25, 0.46, 0.45, 0.94] }}
                  >
                    <NoteSlot note={note} onTagClick={onTagClick} />
                  </motion.div>
                ))}

                {/* Обычные ноты */}
                {col.map(note => {
                  const isNew = !knownIdsRef.current.has(note.id)
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
                      <NoteCard note={note} isNew={isNew} onTagClick={onTagClick} />
                    </motion.div>
                  )
                })}
              </AnimatePresence>
            </div>
          )
        })}
      </div>
    </DragProvider>
  )
}
