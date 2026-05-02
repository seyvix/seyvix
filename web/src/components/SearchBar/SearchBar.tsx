import { Search, X } from 'lucide-react'
import { getTagColor } from '../../utils/tagColor'
import styles from './SearchBar.module.css'

interface SearchBarProps {
  search: string
  activeTags: string[]
  onSearchChange: (value: string) => void
  onTagRemove: (tag: string) => void
  onClear: () => void
}

export function SearchBar({ search, activeTags, onSearchChange, onTagRemove, onClear }: SearchBarProps) {
  const hasContent = search.length > 0 || activeTags.length > 0

  return (
    <label className={styles.bar}>
      <Search size={26} className={styles.icon} />
      <div className={styles.content}>
        {activeTags.map(tag => {
          const { bg, text } = getTagColor(tag)
          return (
            <span key={tag} className={styles.chip} style={{ background: bg, color: text }}>
              {tag}
              <button
                className={styles.chipRemove}
                style={{ color: text }}
                onClick={e => { e.preventDefault(); onTagRemove(tag) }}
              >
                <X size={13} />
              </button>
            </span>
          )
        })}
        <input
          className={styles.input}
          placeholder="Поиск…"
          value={search}
          onChange={e => onSearchChange(e.target.value)}
          onKeyDown={e => {
            if ((e.key === 'Backspace' || e.key === 'Delete') && search === '' && activeTags.length > 0) {
              onTagRemove(activeTags[activeTags.length - 1])
            }
          }}
        />
      </div>
      {hasContent && (
        <button
          className={styles.clearBtn}
          onClick={e => { e.preventDefault(); onClear() }}
          aria-label="Очистить поиск"
        >
          <X size={32} strokeWidth={2.5} />
        </button>
      )}
    </label>
  )
}
