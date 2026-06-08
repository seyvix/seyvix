import { useInfiniteQuery } from '@tanstack/react-query'
import { fetchNotesPage, NOTES_PAGE_SIZE } from '../api/notes.ts'
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

export function hasNotesSearchOrFilters(params: NotesParams = {}) {
  return Boolean(
    params.search
    || params.tags?.length
    || params.folders?.length
    || params.contentTypes?.length
    || params.sources?.length
    || params.favorite !== undefined && params.favorite !== null
    || params.createdAfter
    || params.createdBefore,
  )
}

export function notesRefetchInterval(
  params: NotesParams = {},
  visibilityState: DocumentVisibilityState = 'visible',
) {
  if (hasNotesSearchOrFilters(params)) return false
  return visibilityState === 'visible' ? 5_000 : false
}

export function useNotes(params: NotesParams = {}) {
  const hasSearchOrFilters = hasNotesSearchOrFilters(params)
  const stableParams = notesQueryKey(params)[1]
  const query = useInfiniteQuery({
    queryKey: notesQueryKey(params),
    queryFn: ({ pageParam, signal }) => fetchNotesPage(params, signal, {
      limit: NOTES_PAGE_SIZE,
      offset: pageParam,
    }),
    initialPageParam: 0,
    getNextPageParam: page => page.nextOffset ?? undefined,
    staleTime: hasSearchOrFilters ? 5_000 : 10_000,
    placeholderData: previousData => previousData,
    refetchInterval: () => notesRefetchInterval(
      stableParams,
      typeof document !== 'undefined' ? document.visibilityState : 'visible',
    ),
    refetchOnWindowFocus: 'always',
  })

  return {
    ...query,
    data: query.data?.pages.flatMap(page => page.items),
  }
}
