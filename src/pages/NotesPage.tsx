import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useNotes } from '../hooks/useNotes'
import { NoteGrid } from '../components/NoteGrid/NoteGrid'
import { SearchBar } from '../components/SearchBar/SearchBar'

export default function NotesPage() {
  const [searchParams, setSearchParams] = useSearchParams()

  const search     = searchParams.get('search') ?? ''
  const activeTags = searchParams.get('tags')?.split(',').filter(Boolean) ?? []

  // Локальный state для инпута — не теряем фокус при каждом нажатии
  const [inputValue, setInputValue] = useState(search)
  useEffect(() => { setInputValue(search) }, [search])

  const { data: notes = [], isPending } = useNotes({
    search:  search  || undefined,
    tags:    activeTags.length ? activeTags : undefined,
  })

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

  return (
    <>
      <SearchBar
        search={inputValue}
        activeTags={activeTags}
        onSearchChange={handleSearchChange}
        onTagRemove={handleTagRemove}
        onClear={handleClear}
      />
      {!isPending && (
        <NoteGrid notes={notes} onTagClick={handleTagClick} />
      )}
    </>
  )
}
