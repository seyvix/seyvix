import { useMemo, type CSSProperties } from 'react'
import { Link, NavLink, useParams } from 'react-router-dom'
import {
  ArrowRight,
  ChevronRight,
  FileText,
  Hash,
  Layers3,
  ListTree,
  Search,
  Tags,
} from 'lucide-react'
import { useFolder } from '../hooks/useFolder'
import { useFolders } from '../hooks/useFolders'
import type { Folder, FolderNoteSummary } from '../types'
import styles from './FoldersPage.module.css'

interface FlatCategory {
  category: Folder
  depth: number
}

function categoryUrl(path: string): string {
  return `/categories/${path.split('/').map(encodeURIComponent).join('/')}`
}

function notesUrl(path: string): string {
  return `/notes?folders=${encodeURIComponent(path)}`
}

function flattenCategories(categories: Folder[], depth = 0): FlatCategory[] {
  return categories.flatMap(category => [
    { category, depth },
    ...flattenCategories(category.children, depth + 1),
  ])
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

function CategoryTree({
  categories,
  selectedPath,
}: {
  categories: FlatCategory[]
  selectedPath: string
}) {
  if (categories.length === 0) {
    return (
      <div className={styles.emptyTree}>
        <ListTree size={18} strokeWidth={1.8} />
        <span>Категории появятся после настройки таксономии.</span>
      </div>
    )
  }

  return (
    <nav className={styles.tree} aria-label="Категории">
      {categories.map(({ category, depth }) => (
        <NavLink
          key={category.id}
          to={categoryUrl(category.path)}
          className={({ isActive }) =>
            [styles.treeItem, isActive || selectedPath === category.path ? styles.treeItemActive : '']
              .filter(Boolean)
              .join(' ')
          }
          style={{ '--depth': depth } as CSSProperties}
        >
          <span className={styles.treeRail} />
          <span className={styles.treeName}>{category.name}</span>
          {category.children.length > 0 && (
            <span className={styles.treeCount}>{category.children.length}</span>
          )}
        </NavLink>
      ))}
    </nav>
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

function NoteRow({ note }: { note: FolderNoteSummary }) {
  return (
    <Link to={`/notes/${note.slug}`} className={styles.noteRow}>
      <span className={styles.noteIcon}><FileText size={15} strokeWidth={1.8} /></span>
      <span className={styles.noteBody}>
        <strong>{note.title}</strong>
        <small>{new Date(note.updatedAt).toLocaleDateString('ru-RU')}</small>
      </span>
      <ArrowRight size={14} strokeWidth={1.8} />
    </Link>
  )
}

export default function FoldersPage() {
  const { '*': selectedPath = '' } = useParams()
  const { data: categories = [], isPending: treePending, isError: treeError } = useFolders()
  const {
    data: detail,
    isPending: detailPending,
    isError: detailError,
  } = useFolder(selectedPath)

  const flatCategories = useMemo(() => flattenCategories(categories), [categories])
  const totalCategories = useMemo(() => countCategories(categories), [categories])
  const selectedFromTree = useMemo(
    () => selectedPath ? findCategory(categories, selectedPath) : null,
    [categories, selectedPath],
  )
  const selectedCategory = detail?.category ?? selectedFromTree
  const childCategories = selectedFromTree?.children ?? selectedCategory?.children ?? categories
  const notes = detail?.notes ?? []

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
            <CategoryTree categories={flatCategories} selectedPath={selectedPath} />
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
              </div>

              {detailPending && <div className={styles.state}>Загружаю содержимое категории...</div>}
              {detailError && <div className={styles.stateError}>Не удалось загрузить содержимое категории.</div>}

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
                    <span>{notes.length}</span>
                  </div>
                  {notes.length > 0 ? (
                    <div className={styles.notesList}>
                      {notes.map(note => (
                        <NoteRow key={note.id} note={note} />
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
