import { useCallback, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Trash2 } from 'lucide-react'
import { deleteNotes } from '../api/notes'
import { LoaderSpinner } from '../components/LoaderSpinner'
import { DeferredLinkSnapshotsPanel } from '../components/NoteDetail/DeferredLinkSnapshotsPanel'
import { DetailSourcePanel, TagChips } from '../components/NoteDetail/DetailParts'
import { DetailStream, type DetailStreamHandlers } from '../components/NoteDetail/DetailStream'
import { EnrichmentPanel } from '../components/NoteDetail/EnrichmentPanel'
import { formatDetailDate, noteTypeLabel } from '../components/NoteDetail/format'
import { NoteOverview } from '../components/NoteDetail/NoteOverview'
import { RecommendationsPanel } from '../components/NoteDetail/RecommendationsPanel'
import { useNote } from '../hooks/useNote'
import { useRemoveCollectionItems } from '../hooks/useRemoveCollectionItems'
import { SEARCH_CAPABILITIES_QUERY_KEY } from '../hooks/useSearchCapabilities'
import { useUpdateNote } from '../hooks/useUpdateNote'
import type { Note, NoteObject } from '../types'
import { toggleMarkdownTask } from '../utils/markdownBlocks'
import { getNoteDetailModel, getNoteDisplayTitle } from '../utils/noteCardPresentation'
import styles from './NotePage.module.css'

interface EditState {
  title: string
  texts: Record<string, string>
  deletedIds: ReadonlySet<string>
  removedSlugs: ReadonlySet<string>
}

const NO_IDS: ReadonlySet<string> = new Set()

function DeleteConfirm({ note, onCancel }: { note: Note; onCancel: () => void }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const deleteNote = useMutation({
    mutationFn: () => deleteNotes([note.slug]),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['notes'] }),
        queryClient.invalidateQueries({ queryKey: ['notes-trash'] }),
        // Parent collections cached as ['note', parentId] still list this child.
        queryClient.invalidateQueries({ queryKey: ['note'] }),
        queryClient.invalidateQueries({ queryKey: SEARCH_CAPABILITIES_QUERY_KEY }),
      ])
      navigate('/notes')
    },
  })

  return (
    <div className={styles.deleteConfirm}>
      <div>
        <strong>Удалить заметку?</strong>
        <span>Заметка попадёт в корзину, если она включена в настройках.</span>
      </div>
      <button type="button" className={styles.editBtn} onClick={onCancel}>Отмена</button>
      <button type="button" className={styles.deleteNoteBtn} disabled={deleteNote.isPending} onClick={() => deleteNote.mutate()}>
        <Trash2 size={14} />
        {deleteNote.isPending ? 'Удаляю...' : 'Удалить'}
      </button>
      {deleteNote.isError && <span className={styles.deleteError}>Не удалось удалить заметку.</span>}
    </div>
  )
}

export default function NotePage() {
  const { noteId: routeNoteId = '' } = useParams<{ noteId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { data: note, isLoading, isError } = useNote(routeNoteId)
  const { mutate: updateNote } = useUpdateNote()
  const { mutate: removeItems } = useRemoveCollectionItems()

  const [edit, setEdit] = useState<EditState | null>(null)
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const [chosenViewerId, setChosenViewerId] = useState<string | null>(null)
  const isEditing = edit !== null
  const deletedIds = edit?.deletedIds ?? NO_IDS

  const visibleObjects = useMemo(
    () => note?.objects.filter(obj => !deletedIds.has(obj.id)) ?? [],
    [note, deletedIds],
  )
  const detailModel = useMemo(
    () => (note ? getNoteDetailModel({ ...note, objects: visibleObjects }) : null),
    [note, visibleObjects],
  )

  // The first link/document viewer is expanded by default until the user opens another one.
  const openViewerId = visibleObjects.some(obj => obj.id === chosenViewerId)
    ? chosenViewerId
    : visibleObjects.find(obj => obj.type === 'link' || obj.type === 'document')?.id ?? null

  const handlers = useMemo<DetailStreamHandlers>(() => ({
    onOpenViewer: setChosenViewerId,
    onTextChange: (id, value) => setEdit(prev => (prev ? { ...prev, texts: { ...prev.texts, [id]: value } } : prev)),
    onRemove: (id, slug) => setEdit(prev => (prev
      ? {
          ...prev,
          deletedIds: new Set([...prev.deletedIds, id]),
          removedSlugs: slug ? new Set([...prev.removedSlugs, slug]) : prev.removedSlugs,
        }
      : prev)),
    onToggleTextTask: (obj: NoteObject, taskIndex: number, checked: boolean) => {
      const current = note
      if (!current) return
      const content = toggleMarkdownTask(obj.content, taskIndex, checked)
      if (content === obj.content) return
      const nextObject = { ...obj, content }
      queryClient.setQueryData<Note>(['note', routeNoteId], {
        ...current,
        objects: current.objects.map(item => (item.id === obj.id ? nextObject : item)),
      })
      updateNote(
        { noteRef: obj.noteId ?? obj.slug ?? current.id, data: { objects: [nextObject] } },
        { onSettled: () => queryClient.invalidateQueries({ queryKey: ['note'] }) },
      )
    },
  }), [note, queryClient, routeNoteId, updateNote])

  const enterEdit = useCallback(() => {
    if (!note) return
    setDeleteConfirmOpen(false)
    setEdit({
      title: note.title,
      texts: Object.fromEntries(note.objects.filter(obj => obj.type === 'text').map(obj => [obj.id, obj.content])),
      deletedIds: NO_IDS,
      removedSlugs: NO_IDS,
    })
  }, [note])

  function saveEdit() {
    if (!note || !edit) return
    const title = edit.title.trim() || note.title
    const applySaved = { onSuccess: (saved: Note) => queryClient.setQueryData(['note', routeNoteId], saved) }
    if (note.type === 'collection') {
      if (edit.removedSlugs.size > 0) removeItems({ collectionSlug: note.slug, itemSlugs: [...edit.removedSlugs] })
      updateNote({ noteRef: note.id, data: { title } }, applySaved)
    } else {
      const objects = note.objects
        .filter(obj => !edit.deletedIds.has(obj.id))
        .map(obj => (obj.type === 'text' ? { ...obj, content: edit.texts[obj.id] ?? obj.content } : obj))
      updateNote({ noteRef: note.id, data: { title, objects } }, applySaved)
    }
    setEdit(null)
  }

  if (isLoading) {
    return (
      <div className={styles.page}>
        <div className={styles.notFound}><LoaderSpinner /></div>
      </div>
    )
  }

  if (!note || !detailModel) {
    return (
      <div className={styles.page}>
        <div className={styles.notFound}>{isError ? 'Не удалось загрузить заметку' : 'Заметка не найдена'}</div>
      </div>
    )
  }

  const firstText = visibleObjects.find(obj => obj.type === 'text')
  const displayTitle = getNoteDisplayTitle(note, firstText?.content)

  return (
    <div className={styles.page}>
      <div className={styles.topBar}>
        <button type="button" className={styles.backBtn} onClick={() => navigate(-1)}>
          <ArrowLeft size={14} /> Заметки
        </button>
        <div className={styles.topBarActions}>
          {isEditing ? (
            <>
              <button type="button" className={styles.editBtn} onClick={() => setEdit(null)}>Отмена</button>
              <button type="button" className={styles.saveBtn} onClick={saveEdit}>Сохранить</button>
            </>
          ) : (
            <>
              <button type="button" className={styles.editBtn} onClick={enterEdit}>Редактировать</button>
              <button type="button" className={styles.deleteNoteBtn} onClick={() => setDeleteConfirmOpen(value => !value)}>
                <Trash2 size={14} />
                Удалить
              </button>
            </>
          )}
        </div>
      </div>

      {deleteConfirmOpen && !isEditing && <DeleteConfirm note={note} onCancel={() => setDeleteConfirmOpen(false)} />}

      <div className={styles.content}>
        <div className={styles.detailLayout}>
          <main className={styles.detailMain}>
            <div className={styles.meta}>
              <div className={styles.metaKicker}>
                <span>{noteTypeLabel(note.type)}</span>
                <span>{formatDetailDate(note.createdAt) ?? 'нет даты'}</span>
              </div>
              {edit ? (
                <input
                  autoFocus
                  className={styles.titleInput}
                  value={edit.title}
                  onChange={event => setEdit({ ...edit, title: event.target.value })}
                  onKeyDown={event => { if (event.key === 'Enter') saveEdit() }}
                />
              ) : displayTitle && <h1 className={styles.title}>{displayTitle}</h1>}
              <div className={styles.metaRow}>
                <TagChips tags={note.tags} />
                {note.taxonomyCategory && <span className={styles.countBadge}>{note.taxonomyCategory.path}</span>}
                {note.type === 'collection' && <span className={styles.countBadge}>{visibleObjects.length} элементов</span>}
              </div>
            </div>

            {detailModel.source && <DetailSourcePanel source={detailModel.source} />}

            <DetailStream
              items={detailModel.objects}
              isEditing={isEditing}
              canEditText={note.type !== 'collection'}
              editTexts={edit?.texts ?? {}}
              openViewerId={openViewerId}
              handlers={handlers}
            />
          </main>

          <aside className={styles.detailSidebar}>
            <NoteOverview note={note} objects={visibleObjects} />
            <RecommendationsPanel note={note} />
            <DeferredLinkSnapshotsPanel note={note} />
            <EnrichmentPanel note={note} />
          </aside>
        </div>
      </div>
    </div>
  )
}
