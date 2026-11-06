import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { Check, X } from 'lucide-react'
import { deleteCategory, updateCategory } from '../../api/folders'
import type { Folder } from '../../types'
import { categoryUrl } from './categoryModel'
import styles from './Categories.module.css'

export function CategoryRenameForm({ category, onDone }: { category: Folder; onDone: () => void }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [name, setName] = useState(category.name)
  const rename = useMutation({
    mutationFn: () => updateCategory(category.id, { name }),
    onSuccess: updated => {
      onDone()
      queryClient.invalidateQueries({ queryKey: ['folders'] })
      queryClient.invalidateQueries({ queryKey: ['category', category.path] })
      navigate(categoryUrl(updated.path))
    },
  })

  return (
    <>
      <div className={styles.categoryForm}>
        <input value={name} onChange={event => setName(event.target.value)} placeholder="Новое название" />
        <button
          type="button"
          className={styles.primaryAction}
          disabled={!name.trim() || rename.isPending}
          onClick={() => rename.mutate()}
        >
          <Check size={15} strokeWidth={1.8} />
          Сохранить
        </button>
      </div>
      {rename.isError && <div className={styles.stateError}>Не удалось переименовать категорию: {rename.error.message}</div>}
    </>
  )
}

/** Delete (notes move to Inbox) or delete-with-notes guarded by typing the name and path. */
export function CategoryDeletePanel({ category }: { category: Folder }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [confirmName, setConfirmName] = useState('')
  const [confirmPath, setConfirmPath] = useState('')
  const remove = useMutation({
    mutationFn: (withNotes: boolean) => deleteCategory(category.id, withNotes
      ? { deleteNotes: true, confirmCategoryName: confirmName, confirmDeleteNotesText: confirmPath }
      : { deleteNotes: false }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['folders'] })
      queryClient.invalidateQueries({ queryKey: ['notes'] })
      navigate('/categories')
    },
  })

  return (
    <div className={styles.deletePanel}>
      <div className={styles.deletePanelHeader}>
        <strong>Удаление категории</strong>
        <span>По умолчанию заметки из этой категории и её подкатегорий будут перенесены в Inbox.</span>
      </div>
      <button type="button" className={styles.dangerAction} disabled={remove.isPending} onClick={() => remove.mutate(false)}>
        <X size={15} strokeWidth={1.8} />
        Удалить категорию
      </button>

      <div className={styles.dangerDeleteBlock}>
        <div className={styles.deletePanelHeader}>
          <strong>Удалить вместе с заметками</strong>
          <span>Это отдельный режим: введите название и полный путь категории, чтобы подтвердить удаление содержимого.</span>
        </div>
        <div className={styles.categoryForm}>
          <input value={confirmName} onChange={event => setConfirmName(event.target.value)} placeholder={`Название: ${category.name}`} />
          <input value={confirmPath} onChange={event => setConfirmPath(event.target.value)} placeholder={`Путь: ${category.path}`} />
        </div>
        <button
          type="button"
          className={styles.dangerAction}
          disabled={remove.isPending || confirmName !== category.name || confirmPath !== category.path}
          onClick={() => remove.mutate(true)}
        >
          <X size={15} strokeWidth={1.8} />
          Удалить категорию и заметки
        </button>
      </div>
      {remove.isError && <div className={styles.stateError}>Не удалось удалить категорию: {remove.error.message}</div>}
    </div>
  )
}
