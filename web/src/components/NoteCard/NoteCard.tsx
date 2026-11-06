import { memo, useEffect, useRef, useState } from 'react'
import { Check, RefreshCw } from 'lucide-react'
import { dropTargetForExternal } from '@atlaskit/pragmatic-drag-and-drop/external/adapter'
import { containsFiles, getFiles } from '@atlaskit/pragmatic-drag-and-drop/external/file'
import { LoaderSpinner } from '../LoaderSpinner'
import type { Note } from '../../types'
import { useBulkSelect } from '../../contexts/BulkSelectContext'
import { useSyncLocalNote } from '../../hooks/useSyncLocalNote'
import type { TagClickHandler } from './CardParts'
import { CollectionCard } from './CollectionCard'
import { CompositeCard } from './CompositeCard'
import { SimpleCard } from './SimpleCard'
import { useNoteCardActions } from './NoteCardActions'
import styles from './NoteCard.module.css'

/** Dropping files sooner than this creates a new note; hovering longer appends them to this note. */
const FILE_HOVER_THRESHOLD_MS = 750
/** Freshly created notes glow for this long. */
const HIGHLIGHT_MS = 5000

type FileHoverState = 'new' | 'merge' | null

function useFileDropTarget(noteId: string, disabled: boolean) {
  const ref = useRef<HTMLDivElement>(null)
  const [hoverState, setHoverState] = useState<FileHoverState>(null)
  const { acceptFiles, uploadFiles, addFilesToNote } = useNoteCardActions()

  useEffect(() => {
    const element = ref.current
    if (!element || disabled) return
    let enteredAt = 0
    let timer: number | undefined
    const cleanup = dropTargetForExternal({
      element,
      canDrop: containsFiles,
      onDragEnter: () => {
        enteredAt = Date.now()
        setHoverState('new')
        timer = window.setTimeout(() => setHoverState('merge'), FILE_HOVER_THRESHOLD_MS)
      },
      onDragLeave: () => {
        window.clearTimeout(timer)
        setHoverState(null)
      },
      onDrop: ({ source }) => {
        window.clearTimeout(timer)
        setHoverState(null)
        const accepted = acceptFiles(getFiles({ source }))
        if (accepted.length === 0) return
        if (Date.now() - enteredAt < FILE_HOVER_THRESHOLD_MS) uploadFiles(accepted)
        else addFilesToNote(noteId, accepted)
      },
    })
    return () => {
      window.clearTimeout(timer)
      cleanup()
    }
  }, [noteId, disabled, acceptFiles, uploadFiles, addFilesToNote])

  return { ref, hoverState }
}

function useRecentHighlight(createdAt: string): boolean {
  const [highlighted, setHighlighted] = useState(() => Date.now() - Date.parse(createdAt) < HIGHLIGHT_MS)
  useEffect(() => {
    const remaining = HIGHLIGHT_MS - (Date.now() - Date.parse(createdAt))
    if (!(remaining > 0)) {
      setHighlighted(false)
      return
    }
    setHighlighted(true)
    const timer = setTimeout(() => setHighlighted(false), remaining)
    return () => clearTimeout(timer)
  }, [createdAt])
  return highlighted
}

/** Selection overlay; isolated so toggling selection re-renders only this, not the card body. */
function BulkSelectOverlay({ slug }: { slug: string }) {
  const { isBulk, selectedSlugs, toggleSelect } = useBulkSelect()
  if (!isBulk) return null
  const selected = selectedSlugs.has(slug)
  return (
    <div
      className={selected ? `${styles.bulkOverlay} ${styles.bulkOverlaySelected}` : styles.bulkOverlay}
      role="checkbox"
      aria-checked={selected}
      aria-label="Выбрать заметку"
      onClick={event => {
        event.preventDefault()
        event.stopPropagation()
        toggleSelect(slug)
      }}
    >
      <div className={selected ? `${styles.bulkCheck} ${styles.bulkCheckActive}` : styles.bulkCheck}>
        {selected && <Check size={12} strokeWidth={3} />}
      </div>
    </div>
  )
}

function LocalSyncButton({ note }: { note: Note }) {
  const { mutate: syncLocal, isPending } = useSyncLocalNote()
  return (
    <button
      type="button"
      className={styles.syncBtn}
      title="Синхронизировать с сервером"
      disabled={isPending}
      onClick={event => {
        event.preventDefault()
        event.stopPropagation()
        syncLocal(note)
      }}
    >
      {isPending ? <LoaderSpinner size="xs" /> : <RefreshCw size={14} />}
    </button>
  )
}

/** Grid card: picks the layout for the note type and adds drop/selection/sync affordances. */
export const NoteCard = memo(function NoteCard({ note, onTagClick }: { note: Note; onTagClick?: TagClickHandler }) {
  const { ref, hoverState } = useFileDropTarget(note.id, Boolean(note.isLocal || note.isLoading))
  const highlighted = useRecentHighlight(note.createdAt)

  const className = [
    styles.cardWrapper,
    hoverState === 'new' ? styles.isFileOverNew : '',
    hoverState === 'merge' ? styles.isFileOverMerge : '',
    highlighted ? styles.isHighlighted : '',
  ].filter(Boolean).join(' ')

  return (
    <div ref={ref} className={className}>
      {note.type === 'collection'
        ? <CollectionCard note={note} onTagClick={onTagClick} />
        : note.type === 'composite'
          ? <CompositeCard note={note} onTagClick={onTagClick} />
          : <SimpleCard note={note} onTagClick={onTagClick} />}
      {note.isLoading && (
        <div className={styles.cardLoadingOverlay} aria-hidden>
          <LoaderSpinner className={styles.cardLoadingSpinner} />
        </div>
      )}
      <BulkSelectOverlay slug={note.slug} />
      {note.isLocal && <LocalSyncButton note={note} />}
    </div>
  )
})
