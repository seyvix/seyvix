import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router'
import { Layers3, ListTree, Plus, Search } from 'lucide-react'
import { CategoryCreatePanel } from '../components/Categories/CategoryCreatePanel'
import { CategoryDetail } from '../components/Categories/CategoryDetail'
import { CategoryGrid } from '../components/Categories/CategoryLists'
import { CategoryTree } from '../components/Categories/CategoryTree'
import { ancestorPaths, countCategories, findCategory } from '../components/Categories/categoryModel'
import { useFolders } from '../hooks/useFolders'
import styles from './FoldersPage.module.css'
import shared from '../components/Categories/Categories.module.css'

export default function FoldersPage() {
  const { '*': selectedPath = '' } = useParams()
  const { data: categories = [], isPending: treePending, isError: treeError } = useFolders()
  const [expandedPaths, setExpandedPaths] = useState<ReadonlySet<string>>(() => new Set())
  const [createRootOpen, setCreateRootOpen] = useState(false)
  const [profileWarning, setProfileWarning] = useState<string | null>(null)

  const selectedFromTree = useMemo(
    () => (selectedPath ? findCategory(categories, selectedPath) : null),
    [categories, selectedPath],
  )
  const totalCategories = useMemo(() => countCategories(categories), [categories])

  // Reveal the selected category in the tree.
  useEffect(() => {
    if (!selectedPath) return
    setExpandedPaths(prev => {
      const missing = ancestorPaths(selectedPath).filter(path => !prev.has(path))
      return missing.length ? new Set([...prev, ...missing]) : prev
    })
  }, [selectedPath])

  const toggleExpanded = useCallback((path: string) => {
    setExpandedPaths(prev => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }, [])

  const handleCreated = useCallback((warning: string | null) => {
    setCreateRootOpen(false)
    setProfileWarning(warning)
  }, [])

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
          {treePending && <div className={shared.state}>Загружаю категории...</div>}
          {treeError && <div className={shared.stateError}>Не удалось загрузить категории.</div>}
          {!treePending && !treeError && (categories.length === 0 ? (
            <div className={styles.emptyTree}>
              <ListTree size={18} strokeWidth={1.8} />
              <span>Категории появятся после настройки таксономии.</span>
            </div>
          ) : (
            <CategoryTree
              categories={categories}
              expandedPaths={expandedPaths}
              selectedPath={selectedPath}
              onToggle={toggleExpanded}
            />
          ))}
        </aside>

        <main className={styles.contentPanel}>
          {profileWarning && <div className={shared.stateError}>{profileWarning}</div>}
          {selectedPath ? (
            <CategoryDetail
              key={selectedPath}
              path={selectedPath}
              fallbackCategory={selectedFromTree}
              onCreated={handleCreated}
            />
          ) : (
            <section className={styles.overview}>
              <div className={styles.overviewIntro}>
                <div className={styles.overviewIcon}><Search size={18} strokeWidth={1.8} /></div>
                <div>
                  <h2>Выберите категорию</h2>
                  <p>Откройте раздел дерева слева или начните с одной из корневых категорий.</p>
                </div>
              </div>

              <div className={shared.managementPanel}>
                <div className={shared.sectionHeader}>
                  <h3>Новая корневая категория</h3>
                  <button type="button" className={shared.secondaryAction} onClick={() => setCreateRootOpen(value => !value)}>
                    <Plus size={15} strokeWidth={1.8} />
                    Создать
                  </button>
                </div>
                {createRootOpen && (
                  <CategoryCreatePanel parent={null} title="Создание корневой категории" onCreated={handleCreated} />
                )}
              </div>

              <div className={shared.sectionHeader}>
                <h3>Корневые категории</h3>
                <span>{categories.length}</span>
              </div>
              <CategoryGrid categories={categories} />
            </section>
          )}
        </main>
      </div>
    </div>
  )
}
