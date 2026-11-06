import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { Plus, UploadCloud } from 'lucide-react'
import { dropTargetForExternal } from '@atlaskit/pragmatic-drag-and-drop/external/adapter'
import { containsFiles, getFiles } from '@atlaskit/pragmatic-drag-and-drop/external/file'
import { useDragContext } from '../../contexts/DragContext'
import { useNoteCardActions } from './NoteCardActions'
import styles from './AddNoteCard.module.css'

const loadQuickNoteDialog = () => import('./QuickNoteDialog')
// TipTap/ProseMirror (+ turndown) only load when the user actually opens the editor.
const QuickNoteDialog = lazy(loadQuickNoteDialog)

function preloadQuickNoteDialog() {
  loadQuickNoteDialog().catch(error => console.warn('Failed to preload the note editor', error))
}

/** First grid tile: opens the quick-note editor, or creates a note from dropped files. */
export function AddNoteCard({ onClick }: { onClick?: () => void }) {
  const dropRef = useRef<HTMLDivElement>(null)
  const [isOver, setIsOver] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const { isFileDragging } = useDragContext()
  const { acceptFiles, uploadFiles } = useNoteCardActions()

  useEffect(() => {
    const element = dropRef.current
    if (!element) return
    return dropTargetForExternal({
      element,
      canDrop: containsFiles,
      onDragEnter: () => setIsOver(true),
      onDragLeave: () => setIsOver(false),
      onDrop: ({ source }) => {
        setIsOver(false)
        const accepted = acceptFiles(getFiles({ source }))
        if (accepted.length > 0) uploadFiles(accepted)
      },
    })
  }, [acceptFiles, uploadFiles])

  const showFileMode = (isFileDragging || isOver) && !isEditing
  const className = [
    styles.addCard,
    isOver && !isEditing ? styles.addCardOver : '',
    isFileDragging && !isEditing ? styles.addCardFileDrag : '',
  ].filter(Boolean).join(' ')

  return (
    <>
      <div ref={dropRef} className={className}>
        <button
          type="button"
          className={styles.addCardTrigger}
          onPointerEnter={preloadQuickNoteDialog}
          onFocus={preloadQuickNoteDialog}
          onClick={() => {
            setIsEditing(true)
            onClick?.()
          }}
        >
          {showFileMode
            ? <UploadCloud size={28} className={styles.addIcon} />
            : <Plus size={18} className={styles.addIcon} />}
          <span className={styles.addCardTriggerText}>
            <strong>{isOver ? 'Отпустите файлы' : showFileMode ? 'Бросьте сюда' : 'Новая заметка'}</strong>
            <span>{showFileMode ? 'Создать из файлов' : 'Markdown, вставка из Word, / команды'}</span>
          </span>
        </button>
      </div>
      {isEditing && (
        <Suspense fallback={null}>
          <QuickNoteDialog onClose={() => setIsEditing(false)} />
        </Suspense>
      )}
    </>
  )
}
