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
    contentTypes: params.contentTypes ?? [],
    sources: params.sources ?? [],
    favorite: params.favorite ?? null,
    createdAfter: params.createdAfter ?? null,
    createdBefore: params.createdBefore ?? null,
  }] as const
}

export function useNotes(params: NotesParams = {}) {
  const hasSearchOrFilters = Boolean(
    params.search
    || params.tags?.length
    || params.folders?.length
    || params.contentTypes?.length
    || params.sources?.length
    || params.favorite !== undefined && params.favorite !== null
    || params.createdAfter
    || params.createdBefore,
  )
  return useQuery({
    queryKey: notesQueryKey(params),
    queryFn: ({ signal }) => fetchNotes(params, signal),
    staleTime: hasSearchOrFilters ? 0 : undefined,
    refetchInterval: () => (
      typeof document !== 'undefined' && document.visibilityState === 'visible'
        ? 2000
        : false
    ),
    refetchOnWindowFocus: 'always',
  })
}
