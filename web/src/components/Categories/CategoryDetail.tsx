import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router'
import { Archive, Edit3, FileText, Hash, Layers3, MoreHorizontal, PanelRightOpen, Plus, X } from 'lucide-react'
import { archiveCategory, reclassifyInbox } from '../../api/folders'
import { useFolder } from '../../hooks/useFolder'
import type { Folder } from '../../types'
import { Breadcrumbs, CategoryGrid, CategoryNotesList } from './CategoryLists'
import { CategoryCreatePanel } from './CategoryCreatePanel'
import { CategoryDeletePanel, CategoryRenameForm } from './CategoryManagePanels'
import { CategoryProfileSidebar } from './CategoryProfileSidebar'
import { categoryNotesUrl, INBOX_PATH } from './categoryModel'
import styles from './Categories.module.css'

type OpenPanel = 'create' | 'rename' | 'delete' | null

function ReclassifyButton({ className, pending, onClick }: { className: string; pending: boolean; onClick: () => void }) {
  return (
    <button type="button" className={`${styles.secondaryAction} ${styles.reclassifyAction} ${className}`} disabled={pending} onClick={onClick}>
      <Layers3 size={15} strokeWidth={1.8} />
      {pending ? 'Запускаю...' : 'Перераспределить'}
    </button>
  )
}

/**
 * One category: header actions, management panels, children, popular tags, notes and the
 * profile slide-over. Mounted with `key={category.id}` so all local UI state resets per category.
 */
export function CategoryDetail({
  path,
  fallbackCategory,
  onCreated,
}: {
  path: string
  fallbackCategory: Folder | null
  onCreated: (profileWarning: string | null) => void
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { data: detail, isPending, isError } = useFolder(path)
  const [openPanel, setOpenPanel] = useState<OpenPanel>(null)
  const [moreOpen, setMoreOpen] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)
  const category = detail?.category ?? fallbackCategory
  const isInbox = category?.path === INBOX_PATH

  const reclassify = useMutation({
    mutationFn: reclassifyInbox,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['category', INBOX_PATH] }),
  })
  const archive = useMutation({
    mutationFn: () => archiveCategory(category?.id ?? ''),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['folders'] })
      navigate('/categories')
    },
  })

  if (!category) {
    return isPending
      ? <div className={styles.state}>Загружаю содержимое категории...</div>
      : <div className={styles.stateError}>Категория не найдена.</div>
  }

  const togglePanel = (panel: Exclude<OpenPanel, null>) => {
    setOpenPanel(current => (current === panel ? null : panel))
    setMoreOpen(false)
  }
  const children = fallbackCategory?.children ?? category.children
  const tags = detail?.tags ?? []
  const notes = detail?.notes ?? []

  return (
    <section className={styles.detail}>
      <div className={styles.detailHeader}>
        <div>
          <Breadcrumbs category={category} />
          <div className={styles.detailTitleRow}>
            <h2>{category.name}</h2>
            {isInbox && <ReclassifyButton className={styles.mobileReclassifyAction} pending={reclassify.isPending} onClick={() => reclassify.mutate()} />}
          </div>
          <p>{category.path}</p>
        </div>
        <div className={styles.detailHeaderActions}>
          <button type="button" className={styles.secondaryAction} onClick={() => setProfileOpen(true)}>
            <PanelRightOpen size={16} strokeWidth={1.8} />
            Профиль
          </button>
          <Link className={styles.primaryAction} to={categoryNotesUrl(category.path)}>
            <FileText size={16} strokeWidth={1.8} />
            Заметки
          </Link>
          {isInbox && <ReclassifyButton className={styles.desktopReclassifyAction} pending={reclassify.isPending} onClick={() => reclassify.mutate()} />}
          <div className={styles.moreMenuWrap}>
            <button type="button" className={styles.secondaryAction} aria-expanded={moreOpen} onClick={() => setMoreOpen(value => !value)}>
              <MoreHorizontal size={15} strokeWidth={1.8} />
              Ещё
            </button>
            {moreOpen && (
              <div className={styles.moreMenu}>
                <button type="button" onClick={() => togglePanel('create')}>
                  <Plus size={15} strokeWidth={1.8} />
                  Подкатегория
                </button>
                <button type="button" onClick={() => togglePanel('rename')}>
                  <Edit3 size={15} strokeWidth={1.8} />
                  Переименовать
                </button>
                <button type="button" disabled={isInbox || archive.isPending} onClick={() => archive.mutate()}>
                  <Archive size={15} strokeWidth={1.8} />
                  Архивировать
                </button>
                <button type="button" className={styles.moreDanger} disabled={isInbox} onClick={() => togglePanel('delete')}>
                  <X size={15} strokeWidth={1.8} />
                  Удалить
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {isPending && <div className={styles.state}>Загружаю содержимое категории...</div>}
      {isError && <div className={styles.stateError}>Не удалось загрузить содержимое категории.</div>}
      {isInbox && reclassify.isSuccess && <div className={styles.state}>В очередь отправлено: {reclassify.data.enqueuedCount}</div>}
      {isInbox && reclassify.isError && <div className={styles.stateError}>Не удалось запустить перераспределение inbox.</div>}
      {archive.isError && (
        <div className={styles.stateError}>Не удалось архивировать категорию. Проверьте, нет ли вложенных категорий.</div>
      )}

      <div className={styles.managementPanel}>
        {openPanel === 'create' && (
          <CategoryCreatePanel
            parent={category}
            title={`Подкатегория внутри ${category.name}`}
            onCreated={warning => {
              setOpenPanel(null)
              onCreated(warning)
            }}
          />
        )}
        {openPanel === 'rename' && <CategoryRenameForm category={category} onDone={() => setOpenPanel(null)} />}
        {openPanel === 'delete' && <CategoryDeletePanel category={category} />}
      </div>

      <div className={styles.detailGrid}>
        <section className={styles.detailBlock}>
          <div className={styles.sectionHeader}>
            <h3>Вложенные категории</h3>
            <span>{children.length}</span>
          </div>
          {children.length > 0
            ? <CategoryGrid categories={children} />
            : <div className={styles.emptyBlock}>У этой категории пока нет дочерних категорий.</div>}
        </section>

        <section className={styles.detailBlock}>
          <div className={styles.sectionHeader}>
            <h3>Популярные теги</h3>
            <span>{tags.length}</span>
          </div>
          {tags.length > 0 ? (
            <div className={styles.tags}>
              {tags.slice(0, 12).map(tag => (
                <Link key={tag.id} to={`/notes?tags=${encodeURIComponent(tag.slug ?? tag.name)}`} className={styles.tag}>
                  <Hash size={13} strokeWidth={1.8} />
                  <span>{tag.name}</span>
                  <small>{tag.count ?? 0}</small>
                </Link>
              ))}
            </div>
          ) : (
            <div className={styles.emptyBlock}>Теги появятся, когда в категории будут заметки.</div>
          )}
        </section>

        <section className={styles.detailBlockWide}>
          <div className={styles.sectionHeader}>
            <h3>Заметки</h3>
            <span>{category.directCount} / {category.totalCount}</span>
          </div>
          {notes.length > 0
            ? <CategoryNotesList notes={notes} selectedPath={category.path} />
            : <div className={styles.emptyBlock}>В этой категории пока нет заметок.</div>}
        </section>
      </div>

      {profileOpen && <CategoryProfileSidebar category={category} onClose={() => setProfileOpen(false)} />}
    </section>
  )
}
