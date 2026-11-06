import { memo, type CSSProperties } from 'react'
import { NavLink } from 'react-router'
import { ChevronDown, ChevronRight } from 'lucide-react'
import type { Folder } from '../../types'
import { categoryUrl } from './categoryModel'
import styles from './CategoryTree.module.css'

const CategoryTreeNode = memo(function CategoryTreeNode({
  category,
  depth,
  expandedPaths,
  selectedPath,
  onToggle,
}: {
  category: Folder
  depth: number
  expandedPaths: ReadonlySet<string>
  selectedPath: string
  onToggle: (path: string) => void
}) {
  const hasChildren = category.children.length > 0
  const expanded = expandedPaths.has(category.path)
  const selected = selectedPath === category.path

  return (
    <div>
      <div className={styles.treeRow} style={{ '--depth': depth } as CSSProperties}>
        <button
          type="button"
          className={styles.treeToggle}
          disabled={!hasChildren}
          onClick={() => onToggle(category.path)}
          aria-label={expanded ? 'Свернуть категорию' : 'Развернуть категорию'}
          aria-expanded={hasChildren ? expanded : undefined}
        >
          {hasChildren && (expanded ? <ChevronDown size={14} strokeWidth={1.8} /> : <ChevronRight size={14} strokeWidth={1.8} />)}
        </button>
        <NavLink
          to={categoryUrl(category.path)}
          className={({ isActive }) => (isActive || selected ? `${styles.treeItem} ${styles.treeItemActive}` : styles.treeItem)}
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
})

export function CategoryTree({
  categories,
  expandedPaths,
  selectedPath,
  onToggle,
}: {
  categories: Folder[]
  expandedPaths: ReadonlySet<string>
  selectedPath: string
  onToggle: (path: string) => void
}) {
  return (
    <nav className={styles.tree} aria-label="Категории">
      {categories.map(category => (
        <CategoryTreeNode
          key={category.id}
          category={category}
          depth={0}
          expandedPaths={expandedPaths}
          selectedPath={selectedPath}
          onToggle={onToggle}
        />
      ))}
    </nav>
  )
}
