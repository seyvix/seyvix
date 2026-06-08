import { useQuery } from '@tanstack/react-query'
import { fetchNotes } from '../api/notes.ts'
import type { NotesParams } from '../types/index.ts'

export function notesQueryKey(params: NotesParams = {}) {
  return ['notes', {
    search: params.search ?? null,
    searchMode: params.searchMode ?? null,
    sort: params.sort ?? null,
    tags: params.tags ?? [],
    folders: params.folders ?? [],
  }] as const
}

export function useNotes(params: NotesParams = {}) {
  return useQuery({
    queryKey: notesQueryKey(params),
    queryFn: ({ signal }) => fetchNotes(params, signal),
    staleTime: params.search ? 0 : undefined,
    refetchInterval: () => (
      typeof document !== 'undefined' && document.visibilityState === 'visible'
        ? 2000
        : false
    ),
    refetchOnWindowFocus: 'always',
  })
}
