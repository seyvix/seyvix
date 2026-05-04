import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { RotateCcw, Trash2 } from 'lucide-react'
import { cleanupTrash, fetchTrashNotes, restoreNote } from '../api/notes'
import styles from './TrashPage.module.css'

export default function TrashPage() {
  const queryClient = useQueryClient()
  const { data: notes = [], isPending, isError } = useQuery({
    queryKey: ['notes-trash'],
    queryFn: fetchTrashNotes,
  })
  const restore = useMutation({
    mutationFn: restoreNote,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['notes-trash'] })
      await queryClient.invalidateQueries({ queryKey: ['notes'] })
      await queryClient.invalidateQueries({ queryKey: ['folders'] })
    },
  })
  const cleanup = useMutation({
    mutationFn: cleanupTrash,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['notes-trash'] })
    },
  })

  return (
    <section className={styles.page}>
      <header className={styles.header}>
        <div>
          <p>Корзина</p>
          <h1>Удалённые заметки</h1>
        </div>
        <button className={styles.dangerButton} disabled={cleanup.isPending} onClick={() => cleanup.mutate()}>
          <Trash2 size={16} strokeWidth={1.8} />
          Очистить просроченные
        </button>
      </header>

      {isPending && <div className={styles.state}>Загружаю корзину...</div>}
      {isError && <div className={styles.error}>Не удалось загрузить корзину.</div>}
      {restore.isError && <div className={styles.error}>Не удалось восстановить заметку.</div>}
      {cleanup.isError && <div className={styles.error}>Не удалось очистить корзину.</div>}
      {cleanup.isSuccess && <div className={styles.success}>Удалено просроченных заметок: {cleanup.data.deletedCount}</div>}
      {restore.isSuccess && restore.data && (
        <div className={styles.success}>
          <span>Восстановлено: {restore.data.title}</span>
          <Link to={`/notes/${restore.data.slug}`}>Открыть</Link>
        </div>
      )}

      {!isPending && !isError && (
        <div className={styles.list}>
          {notes.length === 0 ? (
            <div className={styles.state}>Корзина пуста.</div>
          ) : notes.map(note => (
            <article className={styles.row} key={note.id}>
              <div>
                <h2>{note.title}</h2>
                <p>Удалено: {new Date(note.updatedAt).toLocaleDateString('ru-RU')}</p>
              </div>
              <div className={styles.actions}>
                <button disabled={restore.isPending} onClick={() => restore.mutate(note.slug)}>
                  <RotateCcw size={15} strokeWidth={1.8} />
                  Восстановить
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}
