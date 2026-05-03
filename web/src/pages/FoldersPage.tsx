import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, NavLink, useParams } from 'react-router-dom'
import {
  ArrowRight,
  ChevronDown,
  ChevronRight,
  FileText,
  Hash,
  Layers3,
  ListTree,
  Search,
  Tags,
} from 'lucide-react'
import { reclassifyInbox } from '../api/folders'
import { useFolder } from '../hooks/useFolder'
import { useFolders } from '../hooks/useFolders'
import type { Folder, FolderNoteSummary } from '../types'
import styles from './FoldersPage.module.css'

function categoryUrl(path: string): string {
  return `/categories/${path.split('/').map(encodeURIComponent).join('/')}`
}

function notesUrl(path: string): string {
  return `/notes?folders=${encodeURIComponent(path)}`
}

function countCategories(categories: Folder[]): number {
  return categories.reduce((total, category) => total + 1 + countCategories(category.children), 0)
}

function findCategory(categories: Folder[], path: string): Folder | null {
  for (const category of categories) {
    if (category.path === path) return category
    const child = findCategory(category.children, path)
    if (child) return child
  }
  return null
}

function ancestorPaths(path: string): string[] {
  const segments = path.split('/').filter(Boolean)
  return segments.slice(0, -1).map((_, index) => segments.slice(0, index + 1).join('/'))
}

function Breadcrumbs({ category }: { category: Folder }) {
  const segments = category.path.split('/')
  const crumbs = segments.map((segment, index) => ({
    label: segment,
    path: segments.slice(0, index + 1).join('/'),
  }))

  return (
    <div className={styles.breadcrumbs} aria-label="Путь категории">
      {crumbs.map((crumb, index) => (
        <span key={crumb.path} className={styles.crumb}>
          {index > 0 && <ChevronRight size={13} strokeWidth={1.8} />}
          <Link to={categoryUrl(crumb.path)}>{crumb.label}</Link>
        </span>
      ))}
    </div>
  )
}

function CategoryTreeNode({
  category,
  depth,
  expandedPaths,
  selectedPath,
  onToggle,
}: {
  category: Folder
  depth: number
  expandedPaths: Set<string>
  selectedPath: string
  onToggle: (path: string) => void
}) {
  const hasChildren = category.children.length > 0
  const expanded = expandedPaths.has(category.path)

  return (
    <div>
      <div
        className={[
          styles.treeRow,
          selectedPath === category.path ? styles.treeRowActive : '',
        ].filter(Boolean).join(' ')}
        style={{ '--depth': depth } as CSSProperties}
      >
        <button
          className={styles.treeToggle}
          disabled={!hasChildren}
          onClick={() => onToggle(category.path)}
          aria-label={expanded ? 'Свернуть категорию' : 'Развернуть категорию'}
        >
          {hasChildren && (
            expanded ? <ChevronDown size={14} strokeWidth={1.8} /> : <ChevronRight size={14} strokeWidth={1.8} />
          )}
        </button>
        <NavLink
          to={categoryUrl(category.path)}
          className={({ isActive }) =>
            [styles.treeItem, isActive || selectedPath === category.path ? styles.treeItemActive : '']
              .filter(Boolean)
              .join(' ')
          }
        >
          <span className={styles.treeRail} />
          <span className={styles.treeName}>{category.name}</span>
          <span className={styles.treeCount}>{category.totalCount}</span>
        </NavLink>
      </div>

      {hasChildren && expanded && (
        <div className={styles.treeChildren}>
          {category.children.map(child => (
            <CategoryTreeNode
              key={child.id}
              category={child}
              depth={depth + 1}
              expandedPaths={expandedPaths}
              selectedPath={selectedPath}
              onToggle={onToggle}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function CategoryCard({ category }: { category: Folder }) {
  return (
    <Link to={categoryUrl(category.path)} className={styles.categoryCard}>
      <span className={styles.categoryCardIcon}><Tags size={16} strokeWidth={1.8} /></span>
      <span className={styles.categoryCardBody}>
        <strong>{category.name}</strong>
        <small>{category.path}</small>
      </span>
      <ArrowRight size={15} strokeWidth={1.8} />
    </Link>
  )
}

function NoteRow({ note, selectedPath }: { note: FolderNoteSummary; selectedPath: string }) {
  const notePath = note.taxonomyCategory?.path
  const isNested = Boolean(notePath && notePath !== selectedPath)

  return (
    <Link to={`/notes/${note.slug}`} className={styles.noteRow}>
      <span className={styles.noteIcon}><FileText size={15} strokeWidth={1.8} /></span>
      <span className={styles.noteBody}>
        <strong>{note.title}</strong>
        <small>{new Date(note.updatedAt).toLocaleDateString('ru-RU')}</small>
      </span>
      {isNested && <span className={styles.noteCategory}>{notePath}</span>}
      <ArrowRight size={14} strokeWidth={1.8} />
    </Link>
  )
}

export default function FoldersPage() {
  const { '*': selectedPath = '' } = useParams()
  const queryClient = useQueryClient()
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(() => new Set())
  const { data: categories = [], isPending: treePending, isError: treeError } = useFolders()
  const {
    data: detail,
    isPending: detailPending,
    isError: detailError,
  } = useFolder(selectedPath)
  const reclassify = useMutation({
    mutationFn: reclassifyInbox,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['category', 'inbox'] })
    },
  })

  const totalCategories = useMemo(() => countCategories(categories), [categories])
  const selectedFromTree = useMemo(
    () => selectedPath ? findCategory(categories, selectedPath) : null,
    [categories, selectedPath],
  )
  const selectedCategory = detail?.category ?? selectedFromTree
  const childCategories = selectedFromTree?.children ?? selectedCategory?.children ?? categories
  const notes = detail?.notes ?? []

  useEffect(() => {
    if (!selectedPath) return
    setExpandedPaths(prev => {
      const next = new Set(prev)
      ancestorPaths(selectedPath).forEach(path => next.add(path))
      return next
    })
  }, [selectedPath])

  function handleToggle(path: string) {
    setExpandedPaths(prev => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <div className={styles.kicker}>
            <Layers3 size={15} strokeWidth={1.8} />
            Таксономия базы знаний
          </div>
          <h1>Категории</h1>
        </div>
        <div className={styles.headerStats}>
          <div className={styles.stat}>
            <strong>{totalCategories}</strong>
            <span>категорий</span>
          </div>
          <div className={styles.stat}>
            <strong>{categories.length}</strong>
            <span>корневых</span>
          </div>
        </div>
      </header>

      <div className={styles.shell}>
        <aside className={styles.sidebarPanel}>
          <div className={styles.panelHeader}>
            <ListTree size={16} strokeWidth={1.8} />
            <span>Дерево</span>
          </div>
          {treePending && <div className={styles.state}>Загружаю категории...</div>}
          {treeError && <div className={styles.stateError}>Не удалось загрузить категории.</div>}
          {!treePending && !treeError && (
            <nav className={styles.tree} aria-label="Категории">
              {categories.length === 0 ? (
                <div className={styles.emptyTree}>
                  <ListTree size={18} strokeWidth={1.8} />
                  <span>Категории появятся после настройки таксономии.</span>
                </div>
              ) : categories.map(category => (
                <CategoryTreeNode
                  key={category.id}
                  category={category}
                  depth={0}
                  expandedPaths={expandedPaths}
                  selectedPath={selectedPath}
                  onToggle={handleToggle}
                />
              ))}
            </nav>
          )}
        </aside>

        <main className={styles.contentPanel}>
          {!selectedCategory && (
            <section className={styles.overview}>
              <div className={styles.overviewIntro}>
                <div className={styles.overviewIcon}><Search size={18} strokeWidth={1.8} /></div>
                <div>
                  <h2>Выберите категорию</h2>
                  <p>Откройте раздел дерева слева или начните с одной из корневых категорий.</p>
                </div>
              </div>

              <div className={styles.sectionHeader}>
                <h3>Корневые категории</h3>
                <span>{categories.length}</span>
              </div>
              <div className={styles.categoryGrid}>
                {categories.map(category => (
                  <CategoryCard key={category.id} category={category} />
                ))}
              </div>
            </section>
          )}

          {selectedCategory && (
            <section className={styles.detail}>
              <div className={styles.detailHeader}>
                <div>
                  <Breadcrumbs category={selectedCategory} />
                  <h2>{selectedCategory.name}</h2>
                  <p>{selectedCategory.path}</p>
                </div>
                <Link className={styles.primaryAction} to={notesUrl(selectedCategory.path)}>
                  <FileText size={16} strokeWidth={1.8} />
                  Заметки
                </Link>
                {selectedCategory.path === 'inbox' && (
                  <button
                    className={styles.secondaryAction}
                    disabled={reclassify.isPending}
                    onClick={() => reclassify.mutate()}
                  >
                    <Layers3 size={16} strokeWidth={1.8} />
                    {reclassify.isPending ? 'Запускаю...' : 'Перераспределить'}
                  </button>
                )}
              </div>

              {detailPending && <div className={styles.state}>Загружаю содержимое категории...</div>}
              {detailError && <div className={styles.stateError}>Не удалось загрузить содержимое категории.</div>}
              {reclassify.isSuccess && selectedCategory.path === 'inbox' && (
                <div className={styles.state}>
                  В очередь отправлено: {reclassify.data.enqueuedCount}
                </div>
              )}
              {reclassify.isError && selectedCategory.path === 'inbox' && (
                <div className={styles.stateError}>Не удалось запустить перераспределение inbox.</div>
              )}

              <div className={styles.detailGrid}>
                <section className={styles.detailBlock}>
                  <div className={styles.sectionHeader}>
                    <h3>Вложенные категории</h3>
                    <span>{childCategories.length}</span>
                  </div>
                  {childCategories.length > 0 ? (
                    <div className={styles.categoryGrid}>
                      {childCategories.map(category => (
                        <CategoryCard key={category.id} category={category} />
                      ))}
                    </div>
                  ) : (
                    <div className={styles.emptyBlock}>У этой категории пока нет дочерних категорий.</div>
                  )}
                </section>

                <section className={styles.detailBlock}>
                  <div className={styles.sectionHeader}>
                    <h3>Теги внутри категории</h3>
                    <span>{detail?.tags.length ?? 0}</span>
                  </div>
                  {detail?.tags.length ? (
                    <div className={styles.tags}>
                      {detail.tags.map(tag => (
                        <Link key={tag.id} to={`/notes?tags=${encodeURIComponent(tag.slug ?? tag.name)}`} className={styles.tag}>
                          <Hash size={13} strokeWidth={1.8} />
                          {tag.name}
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
                    <span>{selectedCategory.directCount} / {selectedCategory.totalCount}</span>
                  </div>
                  {notes.length > 0 ? (
                    <div className={styles.notesList}>
                      {notes.map(note => (
                        <NoteRow key={note.id} note={note} selectedPath={selectedCategory.path} />
                      ))}
                    </div>
                  ) : (
                    <div className={styles.emptyBlock}>В этой категории пока нет заметок.</div>
                  )}
                </section>
              </div>
            </section>
          )}
        </main>
      </div>
    </div>
  )
}
