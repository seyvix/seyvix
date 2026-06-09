import { useMemo, useState, type CSSProperties, type ReactNode } from 'react'
import {
  CalendarDays,
  Clock3,
  FileText,
  Folder,
  Globe2,
  Info,
  Pin,
  Search,
  Settings,
  SlidersHorizontal,
  Tag as TagIcon,
  X,
} from 'lucide-react'
import { getTagColor } from '../../utils/tagColor'
import type { SearchCapabilities } from '../../api/search'
import {
  parseSearchInput,
  type SearchFilterKey,
  type SearchFilterState,
} from '../../utils/searchQuery'
import styles from './SearchBar.module.css'

export type SearchMode = 'full_text' | 'semantic' | 'hybrid'

export interface SearchFilterOption {
  value: string
  label: string
  description?: string
}

export interface SearchBarFilterOptions {
  tags: SearchFilterOption[]
  folders: SearchFilterOption[]
  types: SearchFilterOption[]
  sources: SearchFilterOption[]
}

export interface AppliedSearchFilter {
  key: SearchFilterKey
  value: string
}

interface SearchBarProps {
  search: string
  filters: SearchFilterState
  filterOptions: SearchBarFilterOptions
  searchMode: SearchMode
  searchHistory: string[]
  capabilities: SearchCapabilities
  onSearchChange: (value: string) => void
  onSearchModeChange: (value: SearchMode) => void
  onHistorySelect: (value: string) => void
  onFilterApply: (filter: AppliedSearchFilter) => void
  onFilterRemove: (filter: AppliedSearchFilter) => void
  onClear: () => void
}

interface Suggestion {
  id: string
  icon: 'filter' | 'tag' | 'category' | 'type' | 'source' | 'pinned' | 'date' | 'mode' | 'history'
  label: string
  description: string
  token: string
  key?: SearchFilterKey
  value?: string
  disabled?: boolean
}

const SEARCH_MODES: Array<{ value: SearchMode; label: string }> = [
  { value: 'hybrid', label: 'Гибридный' },
  { value: 'semantic', label: 'Семантический' },
  { value: 'full_text', label: 'Полнотекстовый' },
]

const FILTER_DEFINITIONS: Array<{
  key: SearchFilterKey
  token: string
  label: string
  description: string
  icon: Suggestion['icon']
}> = [
  { key: 'tag', token: 'tag:', label: 'Тег', description: 'Фильтр по тегу', icon: 'tag' },
  { key: 'category', token: 'category:', label: 'Категория', description: 'Поиск внутри категорий', icon: 'category' },
  { key: 'type', token: 'type:', label: 'Тип', description: 'Заметки, ссылки, PDF, медиа', icon: 'type' },
  { key: 'source', token: 'source:', label: 'Источник', description: 'Telegram, web и другие источники', icon: 'source' },
  { key: 'pinned', token: 'pinned:', label: 'Закреплено', description: 'Избранные материалы', icon: 'pinned' },
  { key: 'after', token: 'after:', label: 'После даты', description: 'Создано после даты', icon: 'date' },
  { key: 'before', token: 'before:', label: 'До даты', description: 'Создано до даты', icon: 'date' },
  { key: 'mode', token: 'mode:', label: 'Режим', description: 'Полнотекстовый, семантический, гибридный', icon: 'mode' },
]

const VECTOR_MODES = new Set<SearchMode>(['semantic', 'hybrid'])

export function SearchBar({
  search,
  filters,
  filterOptions,
  searchMode,
  searchHistory,
  capabilities,
  onSearchChange,
  onSearchModeChange,
  onHistorySelect,
  onFilterApply,
  onFilterRemove,
  onClear,
}: SearchBarProps) {
  const [isModeMenuOpen, setModeMenuOpen] = useState(false)
  const [isSuggestOpen, setSuggestOpen] = useState(false)
  const parsedInput = useMemo(() => parseSearchInput(search), [search])
  const suggestions = useMemo(
    () => buildSuggestions({
      search,
      activeToken: parsedInput.activeToken,
      filterOptions,
      searchHistory,
      capabilities,
      searchMode,
    }),
    [capabilities, filterOptions, parsedInput.activeToken, search, searchHistory, searchMode],
  )

  const activeMode = SEARCH_MODES.find(mode => mode.value === searchMode) ?? SEARCH_MODES[0]
  const unlockedSet = new Set(capabilities.unlockedModes)
  const availableModes = SEARCH_MODES.filter(
    mode => unlockedSet.has(mode.value) || VECTOR_MODES.has(mode.value),
  )
  const anyVectorMode = availableModes.some(mode => VECTOR_MODES.has(mode.value))
  const anyLockedMode = availableModes.some(mode => !unlockedSet.has(mode.value))
  const showModeButton = availableModes.length > 1 || anyVectorMode
  const hasContent = hasSearchContent(search, filters)
  const showSuggestions = isSuggestOpen && suggestions.length > 0

  function applySuggestion(suggestion: Suggestion) {
    if (suggestion.disabled) return
    if (suggestion.icon === 'history') {
      onHistorySelect(suggestion.value ?? suggestion.token)
      setSuggestOpen(false)
      return
    }
    if (suggestion.key && suggestion.value !== undefined) {
      onFilterApply({ key: suggestion.key, value: suggestion.value })
      setSuggestOpen(false)
      return
    }
    onSearchChange(replaceCurrentWord(search, suggestion.token))
  }

  return (
    <div className={styles.bar}>
      <Search size={26} className={styles.icon} />
      <div className={styles.content}>
        <ActiveFilterChips filters={filters} onFilterRemove={onFilterRemove} />
        <input
          className={styles.input}
          type="text"
          role="searchbox"
          name="notes-search"
          autoComplete="off"
          enterKeyHint="search"
          placeholder="Поиск…  tag: category: type: source:"
          value={search}
          onChange={event => {
            onSearchChange(event.target.value)
            setSuggestOpen(true)
          }}
          onFocus={() => setSuggestOpen(true)}
          onBlur={() => {
            window.setTimeout(() => setSuggestOpen(false), 120)
          }}
          onKeyDown={event => {
            if ((event.key === 'Backspace' || event.key === 'Delete') && search === '' && activeChipCount(filters) > 0) {
              event.preventDefault()
              removeLastChip(filters, onFilterRemove)
              return
            }
            if ((event.key === 'Enter' || event.key === 'Tab') && parsedInput.activeToken) {
              const exact = suggestions.find(item => item.value !== undefined && !item.disabled)
              if (exact) {
                event.preventDefault()
                applySuggestion(exact)
                return
              }
              event.preventDefault()
              onFilterApply({
                key: parsedInput.activeToken.canonicalKey,
                value: parsedInput.activeToken.value,
              })
            }
          }}
        />
        {showSuggestions && (
          <div className={styles.suggestMenu}>
            {suggestions.map(item => (
              <button
                key={item.id}
                type="button"
                className={item.disabled ? styles.suggestItemDisabled : styles.suggestItem}
                disabled={item.disabled}
                onPointerDown={event => {
                  event.preventDefault()
                }}
                onMouseDown={event => { event.preventDefault() }}
                onClick={event => {
                  event.preventDefault()
                  applySuggestion(item)
                }}
              >
                <SuggestionIcon icon={item.icon} />
                <span className={styles.suggestText}>
                  <span className={styles.suggestLabel}>{item.label}</span>
                  <span className={styles.suggestDescription}>{item.description}</span>
                </span>
                <code className={styles.suggestToken}>{item.token}</code>
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
            onClick={event => {
              event.preventDefault()
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
                    onClick={event => {
                      event.preventDefault()
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
          type="button"
          className={styles.clearBtn}
          onPointerDown={event => { event.preventDefault(); onClear() }}
          onMouseDown={event => { event.preventDefault() }}
          onClick={event => { event.preventDefault(); onClear() }}
          aria-label="Очистить поиск"
        >
          <X size={32} strokeWidth={2.5} />
        </button>
      )}
    </div>
  )
}

function ActiveFilterChips({
  filters,
  onFilterRemove,
}: {
  filters: SearchFilterState
  onFilterRemove: (filter: AppliedSearchFilter) => void
}) {
  return (
    <>
      {filters.tags.map(tag => {
        const { bg, text } = getTagColor(tag)
        return (
          <FilterChip
            key={`tag:${tag}`}
            label={tag}
            prefix="tag"
            icon={<TagIcon size={13} />}
            style={{ background: bg, color: text }}
            removeColor={text}
            onRemove={() => onFilterRemove({ key: 'tag', value: tag })}
          />
        )
      })}
      {filters.folders.map(folder => (
        <FilterChip
          key={`category:${folder}`}
          label={folder}
          prefix="category"
          icon={<Folder size={13} />}
          onRemove={() => onFilterRemove({ key: 'category', value: folder })}
        />
      ))}
      {filters.contentTypes.map(type => (
        <FilterChip
          key={`type:${type}`}
          label={type}
          prefix="type"
          icon={<FileText size={13} />}
          onRemove={() => onFilterRemove({ key: 'type', value: type })}
        />
      ))}
      {filters.sources.map(source => (
        <FilterChip
          key={`source:${source}`}
          label={source}
          prefix="source"
          icon={<Globe2 size={13} />}
          onRemove={() => onFilterRemove({ key: 'source', value: source })}
        />
      ))}
      {filters.favorite !== null && (
        <FilterChip
          label={String(filters.favorite)}
          prefix="pinned"
          icon={<Pin size={13} />}
          onRemove={() => onFilterRemove({ key: 'pinned', value: String(filters.favorite) })}
        />
      )}
      {filters.createdAfter && (
        <FilterChip
          label={filters.createdAfter}
          prefix="after"
          icon={<CalendarDays size={13} />}
          onRemove={() => onFilterRemove({ key: 'after', value: filters.createdAfter ?? '' })}
        />
      )}
      {filters.createdBefore && (
        <FilterChip
          label={filters.createdBefore}
          prefix="before"
          icon={<CalendarDays size={13} />}
          onRemove={() => onFilterRemove({ key: 'before', value: filters.createdBefore ?? '' })}
        />
      )}
    </>
  )
}

function FilterChip({
  icon,
  prefix,
  label,
  style,
  removeColor,
  onRemove,
}: {
  icon: ReactNode
  prefix: string
  label: string
  style?: CSSProperties
  removeColor?: string
  onRemove: () => void
}) {
  return (
    <span className={styles.chip} style={style}>
      {icon}
      <span className={styles.chipPrefix}>{prefix}:</span>
      <span className={styles.chipValue}>{label}</span>
      <button
        type="button"
        className={styles.chipRemove}
        style={removeColor ? { color: removeColor } : undefined}
        onPointerDown={event => { event.preventDefault(); onRemove() }}
        onMouseDown={event => { event.preventDefault() }}
        onClick={event => { event.preventDefault(); onRemove() }}
        aria-label={`Убрать фильтр ${prefix}:${label}`}
      >
        <X size={13} />
      </button>
    </span>
  )
}

function SuggestionIcon({ icon }: { icon: Suggestion['icon'] }) {
  if (icon === 'history') return <Clock3 size={17} />
  if (icon === 'tag') return <TagIcon size={17} />
  if (icon === 'category') return <Folder size={17} />
  if (icon === 'type') return <FileText size={17} />
  if (icon === 'source') return <Globe2 size={17} />
  if (icon === 'pinned') return <Pin size={17} />
  if (icon === 'date') return <CalendarDays size={17} />
  if (icon === 'mode') return <Settings size={17} />
  return <SlidersHorizontal size={17} />
}

function buildSuggestions({
  search,
  activeToken,
  filterOptions,
  searchHistory,
  capabilities,
  searchMode,
}: {
  search: string
  activeToken: ReturnType<typeof parseSearchInput>['activeToken']
  filterOptions: SearchBarFilterOptions
  searchHistory: string[]
  capabilities: SearchCapabilities
  searchMode: SearchMode
}): Suggestion[] {
  if (activeToken) {
    return valueSuggestions(activeToken.canonicalKey, activeToken.value, {
      filterOptions,
      capabilities,
      searchMode,
    })
  }

  const query = currentWord(search).toLocaleLowerCase()
  const filterSuggestions = FILTER_DEFINITIONS
    .filter(item => !query || item.token.startsWith(query) || item.label.toLocaleLowerCase().includes(query))
    .slice(0, 8)
    .map(item => ({
      id: `filter:${item.key}`,
      icon: item.icon,
      label: item.label,
      description: item.description,
      token: item.token,
    }))

  if (query) return filterSuggestions

  return [
    ...filterSuggestions.slice(0, 6),
    ...searchHistory.filter(Boolean).slice(0, 4).map(item => ({
      id: `history:${item}`,
      icon: 'history' as const,
      label: item,
      description: 'Недавний поиск',
      token: item,
      value: item,
    })),
  ]
}

function valueSuggestions(
  key: SearchFilterKey,
  query: string,
  context: {
    filterOptions: SearchBarFilterOptions
    capabilities: SearchCapabilities
    searchMode: SearchMode
  },
): Suggestion[] {
  const normalizedQuery = query.toLocaleLowerCase()
  if (key === 'tag') return optionSuggestions(key, 'tag', context.filterOptions.tags, normalizedQuery)
  if (key === 'category') return optionSuggestions(key, 'category', context.filterOptions.folders, normalizedQuery)
  if (key === 'type') return optionSuggestions(key, 'type', context.filterOptions.types, normalizedQuery)
  if (key === 'source') return optionSuggestions(key, 'source', context.filterOptions.sources, normalizedQuery)
  if (key === 'pinned') {
    return [
      { value: 'true', label: 'true', description: 'Только избранные' },
      { value: 'false', label: 'false', description: 'Без избранного' },
    ].filter(item => !normalizedQuery || item.value.startsWith(normalizedQuery)).map(item => ({
      id: `pinned:${item.value}`,
      icon: 'pinned',
      label: item.label,
      description: item.description,
      token: `pinned:${item.value}`,
      key,
      value: item.value,
    }))
  }
  if (key === 'mode') {
    const unlocked = new Set(context.capabilities.unlockedModes)
    return SEARCH_MODES
      .filter(item => !normalizedQuery || item.value.includes(normalizedQuery) || item.label.toLocaleLowerCase().includes(normalizedQuery))
      .map(item => ({
        id: `mode:${item.value}`,
        icon: 'mode' as const,
        label: item.label,
        description: item.value === context.searchMode ? 'Текущий режим' : 'Переключить режим поиска',
        token: `mode:${item.value}`,
        key,
        value: item.value,
        disabled: !unlocked.has(item.value),
      }))
  }
  if (key === 'after' || key === 'before') {
    const today = new Date().toISOString().slice(0, 10)
    const examples = [today, '2026-06-01', '2026-05-01']
    return examples
      .filter(item => !normalizedQuery || item.startsWith(normalizedQuery))
      .map(item => ({
        id: `${key}:${item}`,
        icon: 'date' as const,
        label: item,
        description: key === 'after' ? 'Создано после этой даты' : 'Создано до этой даты',
        token: `${key}:${item}`,
        key,
        value: item,
      }))
  }
  return []
}

function optionSuggestions(
  key: SearchFilterKey,
  icon: Suggestion['icon'],
  options: SearchFilterOption[],
  query: string,
): Suggestion[] {
  return options
    .filter(item => {
      if (!query) return true
      return item.value.toLocaleLowerCase().includes(query)
        || item.label.toLocaleLowerCase().includes(query)
        || item.description?.toLocaleLowerCase().includes(query)
    })
    .slice(0, 8)
    .map(item => ({
      id: `${key}:${item.value}`,
      icon,
      label: item.label,
      description: item.description ?? `${key}:${item.value}`,
      token: `${key}:${quoteTokenValue(item.value)}`,
      key,
      value: item.value,
    }))
}

function hasSearchContent(search: string, filters: SearchFilterState): boolean {
  return Boolean(
    search.trim()
    || filters.tags.length
    || filters.folders.length
    || filters.contentTypes.length
    || filters.sources.length
    || filters.favorite !== null
    || filters.createdAfter
    || filters.createdBefore,
  )
}

function activeChipCount(filters: SearchFilterState): number {
  return filters.tags.length
    + filters.folders.length
    + filters.contentTypes.length
    + filters.sources.length
    + (filters.favorite !== null ? 1 : 0)
    + (filters.createdAfter ? 1 : 0)
    + (filters.createdBefore ? 1 : 0)
}

function removeLastChip(
  filters: SearchFilterState,
  onFilterRemove: (filter: AppliedSearchFilter) => void,
) {
  if (filters.createdBefore) onFilterRemove({ key: 'before', value: filters.createdBefore })
  else if (filters.createdAfter) onFilterRemove({ key: 'after', value: filters.createdAfter })
  else if (filters.favorite !== null) onFilterRemove({ key: 'pinned', value: String(filters.favorite) })
  else if (filters.sources.length) onFilterRemove({ key: 'source', value: filters.sources[filters.sources.length - 1] })
  else if (filters.contentTypes.length) onFilterRemove({ key: 'type', value: filters.contentTypes[filters.contentTypes.length - 1] })
  else if (filters.folders.length) onFilterRemove({ key: 'category', value: filters.folders[filters.folders.length - 1] })
  else if (filters.tags.length) onFilterRemove({ key: 'tag', value: filters.tags[filters.tags.length - 1] })
}

function replaceCurrentWord(input: string, replacement: string): string {
  const match = input.match(/(?:^|\s)(\S*)$/)
  if (!match || match.index === undefined) return `${input}${replacement}`
  const startsWithSpace = input[match.index] === ' '
  const start = match.index + (startsWithSpace ? 1 : 0)
  return `${input.slice(0, start)}${replacement}`
}

function currentWord(input: string): string {
  return input.match(/(?:^|\s)(\S*)$/)?.[1] ?? ''
}

function quoteTokenValue(value: string): string {
  if (!/[/"'\s:]/.test(value)) return value
  return `"${value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`
}
