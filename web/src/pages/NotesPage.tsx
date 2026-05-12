import { useState, useEffect, useMemo, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNotes } from '../hooks/useNotes'
import { useLocalNotes } from '../contexts/LocalNotesContext'
import { NoteGrid } from '../components/NoteGrid/NoteGrid'
import { SearchBar } from '../components/SearchBar/SearchBar'
import { BulkToolbar } from '../components/BulkToolbar/BulkToolbar'
import { BulkSelectProvider } from '../contexts/BulkSelectContext'
import { useThumbnailPoller } from '../hooks/useThumbnailPoller'
import { reorderNotes } from '../api/notes'
import type { Note, NotesParams } from '../types'
import { moveSlug, orderBySlugs, type DropPlacement } from '../utils/reorderNotes'

const ORDER_MODE_KEY = 'seyvix:notes-order-mode'

export default function NotesPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()

  const search     = searchParams.get('search') ?? ''
  const activeTags = searchParams.get('tags')?.split(',').filter(Boolean) ?? []
  const activeFolders = searchParams.get('folders')?.split(',').filter(Boolean) ?? []
  const [orderMode, setOrderMode] = useState<'newest' | 'custom'>(() => {
    try {
      return localStorage.getItem(ORDER_MODE_KEY) === 'custom' ? 'custom' : 'newest'
    } catch {
      return 'newest'
    }
  })

  // Локальный state для инпута — не теряем фокус при каждом нажатии
  const [inputValue, setInputValue] = useState(search)
  useEffect(() => { setInputValue(search) }, [search])

  const tagsKey = activeTags.join('\u0001')
  const foldersKey = activeFolders.join('\u0001')
  const notesParams = useMemo<NotesParams>(() => ({
    search: search || undefined,
    tags: activeTags.length ? activeTags : undefined,
    folders: activeFolders.length ? activeFolders : undefined,
    sort: orderMode,
  }), [activeFolders, activeTags, foldersKey, orderMode, search, tagsKey])
  const { data: serverNotes = [], isPending } = useNotes(notesParams)
  const { localNotes } = useLocalNotes()
  const { mutate: persistReorder } = useMutation({
    mutationFn: reorderNotes,
    onError: () => queryClient.invalidateQueries({ queryKey: ['notes'] }),
  })

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

  function handleClear() {
    setInputValue('')
    setSearchParams({})
  }

  const handleMoveNote = useCallback((sourceSlug: string, targetSlug: string, placement: DropPlacement) => {
    const source = serverNotes.find(note => note.slug === sourceSlug)
    const target = serverNotes.find(note => note.slug === targetSlug)
    if (!source || !target) return

    const orderedSlugs = moveSlug(serverNotes.map(note => note.slug), sourceSlug, targetSlug, placement)
    const nextServerNotes = orderBySlugs(serverNotes, orderedSlugs)
    const items = orderedSlugs.map((slug, index) => ({ slug, position: (index + 1) * 10 }))
    const customParams = { ...notesParams, sort: 'custom' as const }

    setOrderMode('custom')
    try { localStorage.setItem(ORDER_MODE_KEY, 'custom') } catch { /* ignore */ }
    queryClient.setQueryData<Note[]>(['notes', notesParams], nextServerNotes)
    queryClient.setQueryData<Note[]>(['notes', customParams], nextServerNotes)
    persistReorder(items)
  }, [notesParams, persistReorder, queryClient, serverNotes])

  return (
    <BulkSelectProvider>
      <SearchBar
        search={inputValue}
        activeTags={activeTags}
        onSearchChange={handleSearchChange}
        onTagRemove={handleTagRemove}
        onClear={handleClear}
      />
      <BulkToolbar />
      {!isPending && (
        <NoteGrid notes={notes} onTagClick={handleTagClick} onMoveNote={handleMoveNote} />
      )}
    </BulkSelectProvider>
  )
}
