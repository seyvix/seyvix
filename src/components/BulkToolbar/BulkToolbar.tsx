import { CheckSquare, Square, Trash2 } from 'lucide-react'
import { useBulkSelect } from '../../contexts/BulkSelectContext'
import { useBulkDeleteNotes } from '../../hooks/useBulkDeleteNotes'
import styles from './BulkToolbar.module.css'

export function BulkToolbar() {
  const { isBulk, selectedSlugs, toggleBulk } = useBulkSelect()
  const { mutate: bulkDelete, isPending } = useBulkDeleteNotes()

  function handleDelete() {
    const slugs = Array.from(selectedSlugs)
    if (slugs.length === 0) return
    bulkDelete(slugs)
  }

  return (
    <div className={styles.toolbar}>
      <button
        className={`${styles.toggleBtn} ${isBulk ? styles.active : ''}`}
        onClick={toggleBulk}
        title={isBulk ? 'Выйти из режима выбора' : 'Включить выбор'}
      >
        {isBulk ? <CheckSquare size={16} /> : <Square size={16} />}
        Выбор
      </button>

      {isBulk && (
        <>
          <span className={styles.count}>
            {selectedSlugs.size > 0
              ? `Выбрано: ${selectedSlugs.size}`
              : 'Нажмите на карточки'}
          </span>

          {selectedSlugs.size > 0 && (
            <button
              className={`${styles.deleteBtn} ${isPending ? styles.deleting : ''}`}
              onClick={handleDelete}
              disabled={isPending}
              title="Удалить выбранные"
            >
              <Trash2 size={14} />
              Удалить ({selectedSlugs.size})
            </button>
          )}
        </>
      )}
    </div>
  )
}
