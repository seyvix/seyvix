import { useState } from 'react'
import { Clock3, Info, Search, Settings, X } from 'lucide-react'
import { getTagColor } from '../../utils/tagColor'
import type { SearchCapabilities } from '../../api/search'
import styles from './SearchBar.module.css'

export type SearchMode = 'full_text' | 'semantic' | 'hybrid'

interface SearchBarProps {
  search: string
  activeTags: string[]
  searchMode: SearchMode
  searchHistory: string[]
  capabilities: SearchCapabilities
  onSearchChange: (value: string) => void
  onSearchModeChange: (value: SearchMode) => void
  onHistorySelect: (value: string) => void
  onTagRemove: (tag: string) => void
  onClear: () => void
}

const SEARCH_MODES: Array<{ value: SearchMode; label: string }> = [
  { value: 'hybrid', label: 'Гибридный' },
  { value: 'semantic', label: 'Семантический' },
  { value: 'full_text', label: 'Полнотекстовый' },
]

const VECTOR_MODES = new Set<SearchMode>(['semantic', 'hybrid'])

export function SearchBar({
  search,
  activeTags,
  searchMode,
  searchHistory,
  capabilities,
  onSearchChange,
  onSearchModeChange,
  onHistorySelect,
  onTagRemove,
  onClear,
}: SearchBarProps) {
  const hasContent = search.length > 0 || activeTags.length > 0
  const [isModeMenuOpen, setModeMenuOpen] = useState(false)
  const [isHistoryOpen, setHistoryOpen] = useState(false)
  const activeMode = SEARCH_MODES.find(mode => mode.value === searchMode) ?? SEARCH_MODES[0]
  const visibleHistory = searchHistory.filter(item => item.trim())

  const unlockedSet = new Set(capabilities.unlockedModes)
  const availableModes = SEARCH_MODES.filter(
    mode => unlockedSet.has(mode.value) || VECTOR_MODES.has(mode.value),
  )
  const anyVectorMode = availableModes.some(mode => VECTOR_MODES.has(mode.value))
  const anyLockedMode = availableModes.some(mode => !unlockedSet.has(mode.value))
  const showModeButton = availableModes.length > 1 || anyVectorMode

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
          onFocus={() => setHistoryOpen(true)}
          onBlur={() => {
            window.setTimeout(() => setHistoryOpen(false), 120)
          }}
          onKeyDown={e => {
            if ((e.key === 'Backspace' || e.key === 'Delete') && search === '' && activeTags.length > 0) {
              onTagRemove(activeTags[activeTags.length - 1])
            }
          }}
        />
        {isHistoryOpen && visibleHistory.length > 0 && (
          <div className={styles.historyMenu}>
            {visibleHistory.map(item => (
              <button
                key={item}
                type="button"
                className={styles.historyItem}
                onMouseDown={e => e.preventDefault()}
                onClick={e => {
                  e.preventDefault()
                  onHistorySelect(item)
                  setHistoryOpen(false)
                }}
              >
                <Clock3 size={13} />
                <span>{item}</span>
              </button>
            ))}
          </div>
        )}
      </div>
      {showModeButton && (
        <div className={styles.mode}>
          <button
            type="button"
            className={styles.modeButton}
            title={`Режим поиска: ${activeMode.label}`}
            aria-label={`Режим поиска: ${activeMode.label}`}
            aria-expanded={isModeMenuOpen}
            onClick={e => {
              e.preventDefault()
              setModeMenuOpen(value => !value)
            }}
          >
            <Settings size={18} />
          </button>
          {isModeMenuOpen && (
            <div className={styles.modeMenu} role="menu">
              {availableModes.map(mode => {
                const locked = !unlockedSet.has(mode.value)
                const isActive = mode.value === searchMode
                const progress = `${capabilities.noteCount} / ${capabilities.threshold}`
                return (
                  <button
                    key={mode.value}
                    type="button"
                    role="menuitemradio"
                    aria-checked={isActive}
                    aria-disabled={locked}
                    disabled={locked}
                    title={locked ? `Доступно после ${progress} заметок` : undefined}
                    className={[
                      isActive ? styles.modeItemActive : styles.modeItem,
                      locked ? styles.modeItemLocked : '',
                    ].filter(Boolean).join(' ')}
                    onClick={e => {
                      e.preventDefault()
                      if (locked) return
                      onSearchModeChange(mode.value)
                      setModeMenuOpen(false)
                    }}
                  >
                    <span>{mode.label}</span>
                    {locked && (
                      <span className={styles.modeProgress}>{progress}</span>
                    )}
                  </button>
                )
              })}
              {anyLockedMode && (
                <div className={styles.modeHint}>
                  <Info size={12} />
                  <span>
                    Векторные режимы открываются после {capabilities.threshold} заметок
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
      )}
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
