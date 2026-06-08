import { useState, useEffect, useMemo, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown } from 'lucide-react'
import { useNotes } from '../hooks/useNotes'
import { useLocalNotes } from '../contexts/LocalNotesContext'
import { NoteGrid } from '../components/NoteGrid/NoteGrid'
import {
  SearchBar,
  type AppliedSearchFilter,
  type SearchBarFilterOptions,
} from '../components/SearchBar/SearchBar'
import type { SearchMode } from '../components/SearchBar/SearchBar'
import { BulkToolbar } from '../components/BulkToolbar/BulkToolbar'
import { BulkSelectProvider } from '../contexts/BulkSelectContext'
import { useThumbnailPoller } from '../hooks/useThumbnailPoller'
import { nextSearchHistory, readSearchHistory, writeSearchHistory } from '../utils/searchHistory'
import { useSearchCapabilities } from '../hooks/useSearchCapabilities'
import { normalizeSearchMode } from '../utils/searchMode'
import {
  parseSearchInput,
  searchFiltersFromParams,
  searchFiltersToParams,
  type SearchFilterState,
} from '../utils/searchQuery'
import { useFolders } from '../hooks/useFolders'
import { fetchTags } from '../api/enrichment'
import type { Folder } from '../types'
import { LoaderSpinner } from '../components/LoaderSpinner'
import styles from './NotesPage.module.css'

const TYPE_OPTIONS = [
  { value: 'note', label: 'Notes', description: 'Текстовые заметки' },
  { value: 'link', label: 'Links', description: 'Сохраненные URL' },
  { value: 'image', label: 'Images', description: 'Изображения' },
  { value: 'video', label: 'Videos', description: 'Видео' },
  { value: 'audio', label: 'Audio', description: 'Аудио' },
  { value: 'pdf', label: 'PDF', description: 'PDF документы' },
  { value: 'document', label: 'Documents', description: 'Файлы и документы' },
  { value: 'collection', label: 'Collections', description: 'Коллекции материалов' },
]

const SOURCE_OPTIONS = [
  { value: 'telegram', label: 'Telegram', description: 'Материалы из Telegram' },
  { value: 'web', label: 'Web', description: 'Веб-источники' },
  { value: 'api', label: 'API', description: 'Импорт через API' },
  { value: 'browser', label: 'Browser', description: 'Браузерное расширение' },
  { value: 'cli', label: 'CLI', description: 'Командная строка' },
  { value: 'mobile', label: 'Mobile', description: 'Мобильное приложение' },
  { value: 'extension', label: 'Extension', description: 'Расширение' },
  { value: 'manual', label: 'Manual', description: 'Создано вручную' },
]

export default function NotesPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const searchParamsKey = searchParams.toString()
  const { capabilities } = useSearchCapabilities()
  const rawSearchMode = searchParams.get('searchMode')
  const searchMode = normalizeSearchMode(rawSearchMode, capabilities)
  const urlFilters = useMemo(
    () => searchFiltersFromParams(searchParams),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [searchParamsKey],
  )
  const filters: SearchFilterState = useMemo(
    () => ({ ...urlFilters, searchMode }),
    [searchMode, urlFilters],
  )
  const search = filters.text

  useEffect(() => {
    if (rawSearchMode && rawSearchMode !== searchMode) {
      setSearchParams(prev => {
        const next = new URLSearchParams(prev)
        if (searchMode === capabilities.defaultMode) next.delete('searchMode')
        else next.set('searchMode', searchMode)
        return next
      }, { replace: true })
    }
  }, [rawSearchMode, searchMode, capabilities.defaultMode, setSearchParams])

  const [inputValue, setInputValue] = useState(search)
  const preserveDraftOnUrlSync = useRef(false)
  const [searchHistory, setSearchHistory] = useState<string[]>(() => readSearchHistory())

  useEffect(() => {
    if (preserveDraftOnUrlSync.current) {
      preserveDraftOnUrlSync.current = false
      return
    }
    setInputValue(search)
  }, [search, searchParamsKey])

  useEffect(() => {
    const trimmed = search.trim()
    if (!trimmed) return
    const timer = window.setTimeout(() => {
      setSearchHistory(current => {
        const next = nextSearchHistory(current, trimmed)
        writeSearchHistory(next)
        return next
      })
    }, 600)
    return () => window.clearTimeout(timer)
  }, [search])

  const { data: folders = [] } = useFolders()
  const { data: tags = [] } = useQuery({
    queryKey: ['tags'],
    queryFn: fetchTags,
  })
  const filterOptions = useMemo<SearchBarFilterOptions>(() => ({
    tags: tags.map(tag => ({
      value: tag.slug,
      label: tag.name,
      description: tag.description ?? tag.slug,
    })),
    folders: flattenFolders(folders).map(folder => ({
      value: folder.path,
      label: folder.name,
      description: folder.path,
    })),
    types: TYPE_OPTIONS,
    sources: SOURCE_OPTIONS,
  }), [folders, tags])

  const notesQuery = useNotes({
    search:  search  || undefined,
    searchMode,
    tags:    filters.tags.length ? filters.tags : undefined,
    folders: filters.folders.length ? filters.folders : undefined,
    contentTypes: filters.contentTypes.length ? filters.contentTypes : undefined,
    sources: filters.sources.length ? filters.sources : undefined,
    favorite: filters.favorite,
    createdAfter: filters.createdAfter,
    createdBefore: filters.createdBefore,
    sort:    'custom',
  })
  const serverNotes = notesQuery.data ?? []
  const { localNotes } = useLocalNotes()

  const pendingNotes  = useMemo(() => localNotes.filter(n => n.isLocal || n.isLoading), [localNotes])
  const pendingIds    = useMemo(() => new Set(pendingNotes.map(n => n.id)), [pendingNotes])
  const notes = useMemo(
    () => [...pendingNotes, ...serverNotes.filter(n => !pendingIds.has(n.id))],
    [pendingNotes, serverNotes, pendingIds],
  )
  const hasActiveSearchOrFilters = hasActiveFilters(filters)
  const isSearchUpdating = hasActiveSearchOrFilters && notesQuery.isFetching && !notesQuery.isFetchingNextPage
  const emptyState = useMemo(() => {
    if (notesQuery.isError) {
      return {
        title: 'Не удалось загрузить заметки',
        description: 'Обнови страницу или попробуй позже.',
      }
    }
    if (hasActiveSearchOrFilters && !notesQuery.isFetching && notes.length === 0) {
      return {
        title: 'Ничего не найдено',
        description: 'Попробуй изменить запрос или убрать часть фильтров.',
      }
    }
    return undefined
  }, [hasActiveSearchOrFilters, notes.length, notesQuery.isError, notesQuery.isFetching])

  useThumbnailPoller(notes, { enabled: !hasActiveSearchOrFilters })

  function applyFilters(nextFilters: SearchFilterState, replace = true) {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      searchFiltersToParams(next, nextFilters, { defaultMode: capabilities.defaultMode })
      return next
    }, { replace })
  }

  function handleSearchChange(value: string) {
    const parsed = parseSearchInput(value)
    const nextFilters = mergeParsedFilters(filters, parsed.filters)
    setInputValue(hasCommittedFilters(parsed.filters) && !parsed.activeToken ? parsed.text : value)
    preserveDraftOnUrlSync.current = Boolean(parsed.activeToken)
    applyFilters(nextFilters, true)
  }

  function handleHistorySelect(value: string) {
    const nextFilters = { ...filters, text: value }
    setInputValue(value)
    applyFilters(nextFilters, true)
  }

  function handleTagClick(tag: string) {
    handleFilterApply({ key: 'tag', value: tag })
  }

  function handleFilterApply(filter: AppliedSearchFilter) {
    const parsed = parseSearchInput(inputValue)
    let nextFilters = { ...filters, text: parsed.text }
    if (filter.key === 'tag') {
      nextFilters = { ...nextFilters, tags: appendUnique(nextFilters.tags, filter.value) }
    } else if (filter.key === 'category') {
      nextFilters = { ...nextFilters, folders: appendUnique(nextFilters.folders, filter.value) }
    } else if (filter.key === 'type') {
      nextFilters = { ...nextFilters, contentTypes: appendUnique(nextFilters.contentTypes, filter.value.toLocaleLowerCase()) }
    } else if (filter.key === 'source') {
      nextFilters = { ...nextFilters, sources: appendUnique(nextFilters.sources, filter.value.toLocaleLowerCase()) }
    } else if (filter.key === 'pinned') {
      nextFilters = { ...nextFilters, favorite: parseBooleanFilter(filter.value) }
    } else if (filter.key === 'after') {
      nextFilters = { ...nextFilters, createdAfter: filter.value }
    } else if (filter.key === 'before') {
      nextFilters = { ...nextFilters, createdBefore: filter.value }
    } else if (filter.key === 'mode' && isSearchMode(filter.value)) {
      nextFilters = { ...nextFilters, searchMode: filter.value }
    }
    setInputValue(nextFilters.text)
    preserveDraftOnUrlSync.current = false
    applyFilters(nextFilters, true)
  }

  function handleFilterRemove(filter: AppliedSearchFilter) {
    let nextFilters = filters
    if (filter.key === 'tag') {
      nextFilters = { ...filters, tags: filters.tags.filter(value => value !== filter.value) }
    } else if (filter.key === 'category') {
      nextFilters = { ...filters, folders: filters.folders.filter(value => value !== filter.value) }
    } else if (filter.key === 'type') {
      nextFilters = { ...filters, contentTypes: filters.contentTypes.filter(value => value !== filter.value) }
    } else if (filter.key === 'source') {
      nextFilters = { ...filters, sources: filters.sources.filter(value => value !== filter.value) }
    } else if (filter.key === 'pinned') {
      nextFilters = { ...filters, favorite: null }
    } else if (filter.key === 'after') {
      nextFilters = { ...filters, createdAfter: null }
    } else if (filter.key === 'before') {
      nextFilters = { ...filters, createdBefore: null }
    } else if (filter.key === 'mode') {
      nextFilters = { ...filters, searchMode: capabilities.defaultMode }
    }
    applyFilters(nextFilters, true)
  }

  function handleSearchModeChange(value: SearchMode) {
    applyFilters({ ...filters, searchMode: value }, true)
  }

  function handleClear() {
    setInputValue('')
    preserveDraftOnUrlSync.current = false
    navigate('/notes', { replace: true })
  }

  return (
    <BulkSelectProvider>
      <SearchBar
        search={inputValue}
        filters={filters}
        filterOptions={filterOptions}
        searchMode={searchMode}
        searchHistory={searchHistory}
        capabilities={capabilities}
        onSearchChange={handleSearchChange}
        onSearchModeChange={handleSearchModeChange}
        onHistorySelect={handleHistorySelect}
        onFilterApply={handleFilterApply}
        onFilterRemove={handleFilterRemove}
        onClear={handleClear}
      />
      <BulkToolbar />
      <NoteGrid
        notes={notes}
        preserveOrder={!hasActiveSearchOrFilters}
        showAddCard={!hasActiveSearchOrFilters}
        isUpdating={isSearchUpdating}
        updatingLabel="Ищем материалы"
        emptyState={emptyState}
        onTagClick={handleTagClick}
      />
      {notesQuery.hasNextPage && (
        <div className={styles.loadMoreRow}>
          <button
            type="button"
            className={styles.loadMoreButton}
            onClick={() => void notesQuery.fetchNextPage()}
            disabled={notesQuery.isFetchingNextPage}
          >
            {notesQuery.isFetchingNextPage
              ? <LoaderSpinner size="xs" />
              : <ChevronDown size={16} />}
            <span>{notesQuery.isFetchingNextPage ? 'Загружаем' : 'Показать еще'}</span>
          </button>
        </div>
      )}
    </BulkSelectProvider>
  )
}

function flattenFolders(folders: Folder[]): Folder[] {
  return folders.flatMap(folder => [folder, ...flattenFolders(folder.children)])
}

function mergeParsedFilters(
  current: SearchFilterState,
  parsed: SearchFilterState,
): SearchFilterState {
  return {
    ...current,
    text: parsed.text,
    tags: appendUnique([...current.tags, ...parsed.tags]),
    folders: appendUnique([...current.folders, ...parsed.folders]),
    contentTypes: appendUnique([...current.contentTypes, ...parsed.contentTypes]),
    sources: appendUnique([...current.sources, ...parsed.sources]),
    favorite: parsed.favorite === null ? current.favorite : parsed.favorite,
    createdAfter: parsed.createdAfter ?? current.createdAfter,
    createdBefore: parsed.createdBefore ?? current.createdBefore,
    searchMode: parsed.searchMode ?? current.searchMode,
  }
}

function hasCommittedFilters(filters: SearchFilterState): boolean {
  return Boolean(
    filters.tags.length
    || filters.folders.length
    || filters.contentTypes.length
    || filters.sources.length
    || filters.favorite !== null
    || filters.createdAfter
    || filters.createdBefore
    || filters.searchMode,
  )
}

function hasActiveFilters(filters: SearchFilterState): boolean {
  return Boolean(
    filters.text.trim()
    || filters.tags.length
    || filters.folders.length
    || filters.contentTypes.length
    || filters.sources.length
    || filters.favorite !== null
    || filters.createdAfter
    || filters.createdBefore,
  )
}

function appendUnique(values: string[], nextValue?: string): string[] {
  const seen = new Set<string>()
  const result: string[] = []
  for (const raw of nextValue === undefined ? values : [...values, nextValue]) {
    const value = raw.trim()
    if (!value) continue
    const key = value.toLocaleLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    result.push(value)
  }
  return result
}

function parseBooleanFilter(value: string): boolean | null {
  const normalized = value.trim().toLocaleLowerCase()
  if (['true', '1', 'yes', 'on', 'да'].includes(normalized)) return true
  if (['false', '0', 'no', 'off', 'нет'].includes(normalized)) return false
  return null
}

function isSearchMode(value: string): value is SearchMode {
  return value === 'full_text' || value === 'semantic' || value === 'hybrid'
}
