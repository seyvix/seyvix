import { useState, useEffect, useMemo } from 'react'
import { useSearchParams } from 'react-router'
import { useNotes } from '../hooks/useNotes'
import { useLocalNotes } from '../contexts/LocalNotesContext'
import { NoteGrid } from '../components/NoteGrid/NoteGrid'
import { SearchBar } from '../components/SearchBar/SearchBar'
import type { SearchMode } from '../components/SearchBar/SearchBar'
import { BulkToolbar } from '../components/BulkToolbar/BulkToolbar'
import { BulkSelectProvider } from '../contexts/BulkSelectContext'
import { useThumbnailPoller } from '../hooks/useThumbnailPoller'
import { nextSearchHistory, readSearchHistory, writeSearchHistory } from '../utils/searchHistory'
import { useSearchCapabilities } from '../hooks/useSearchCapabilities'
import { normalizeSearchMode } from '../utils/searchMode'

export default function NotesPage() {
  const [searchParams, setSearchParams] = useSearchParams()

  const search     = searchParams.get('search') ?? ''
  const { capabilities } = useSearchCapabilities()
  const rawSearchMode = searchParams.get('searchMode')
  const searchMode = normalizeSearchMode(rawSearchMode, capabilities)

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
  const activeTags = searchParams.get('tags')?.split(',').filter(Boolean) ?? []
  const activeFolders = searchParams.get('folders')?.split(',').filter(Boolean) ?? []

  // Локальный state для инпута — не теряем фокус при каждом нажатии
  const [inputValue, setInputValue] = useState(search)
  const [searchHistory, setSearchHistory] = useState<string[]>(() => readSearchHistory())
  useEffect(() => { setInputValue(search) }, [search])
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

  const { data: serverNotes = [], isPending } = useNotes({
    search:  search  || undefined,
    searchMode,
    tags:    activeTags.length ? activeTags : undefined,
    folders: activeFolders.length ? activeFolders : undefined,
    sort:    'custom',
  })
  const { localNotes } = useLocalNotes()

  // Only truly pending (local/loading) notes occupy a slot and block the server copy.
  // Once a note is confirmed (isLocal=false, isLoading=false) the server version takes over.
  const pendingNotes  = useMemo(() => localNotes.filter(n => n.isLocal || n.isLoading), [localNotes])
  const pendingIds    = useMemo(() => new Set(pendingNotes.map(n => n.id)), [pendingNotes])
  const notes = useMemo(
    () => [...pendingNotes, ...serverNotes.filter(n => !pendingIds.has(n.id))],
    [pendingNotes, serverNotes, pendingIds],
  )

  useThumbnailPoller(notes)

  function handleSearchChange(value: string) {
    setInputValue(value)
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (value) next.set('search', value)
      else next.delete('search')
      return next
    }, { replace: true })
  }

  function handleHistorySelect(value: string) {
    setInputValue(value)
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      next.set('search', value)
      return next
    }, { replace: true })
  }

  function handleTagClick(tag: string) {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      const current = next.get('tags')?.split(',').filter(Boolean) ?? []
      if (!current.includes(tag)) {
        next.set('tags', [...current, tag].join(','))
      }
      return next
    })
  }

  function handleTagRemove(tag: string) {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      const current = next.get('tags')?.split(',').filter(Boolean) ?? []
      const updated = current.filter(t => t !== tag)
      if (updated.length) next.set('tags', updated.join(','))
      else next.delete('tags')
      return next
    })
  }

  function handleSearchModeChange(value: SearchMode) {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (value === capabilities.defaultMode) next.delete('searchMode')
      else next.set('searchMode', value)
      return next
    }, { replace: true })
  }

  function handleClear() {
    setInputValue('')
    setSearchParams({})
  }

  return (
    <BulkSelectProvider>
      <SearchBar
        search={inputValue}
        activeTags={activeTags}
        searchMode={searchMode}
        searchHistory={searchHistory}
        capabilities={capabilities}
        onSearchChange={handleSearchChange}
        onSearchModeChange={handleSearchModeChange}
        onHistorySelect={handleHistorySelect}
        onTagRemove={handleTagRemove}
        onClear={handleClear}
      />
      <BulkToolbar />
      {!isPending && (
        <NoteGrid notes={notes} onTagClick={handleTagClick} />
      )}
    </BulkSelectProvider>
  )
}
