import { useEffect, useRef } from 'react'
import { type InfiniteData, useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { fetchNotesPage, NOTES_PAGE_SIZE } from '../api/notes.ts'
import type { Note, NotesPageResult, NotesParams } from '../types/index.ts'

const HOME_NOTES_POLL_INTERVAL_MS = 2_000

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
  return visibilityState === 'visible' ? HOME_NOTES_POLL_INTERVAL_MS : false
}

type NotesQueryParams = ReturnType<typeof notesQueryKey>[1]
export type NotesInfiniteData = InfiniteData<NotesPageResult, number>
export type NotesQueryData = NotesInfiniteData | Note[] | undefined

function notesParamsFromQueryParams(params: NotesQueryParams): NotesParams {
  return {
    search: params.search ?? undefined,
    searchMode: params.searchMode ?? undefined,
    sort: params.sort ?? undefined,
    tags: params.tags.length ? [...params.tags] : undefined,
    folders: params.folders.length ? [...params.folders] : undefined,
    contentTypes: params.contentTypes.length ? [...params.contentTypes] : undefined,
    sources: params.sources.length ? [...params.sources] : undefined,
    favorite: params.favorite,
    createdAfter: params.createdAfter,
    createdBefore: params.createdBefore,
  }
}

export function dedupeNotes(notes: Note[]) {
  const seen = new Set<string>()
  return notes.filter(note => {
    if (seen.has(note.id)) return false
    seen.add(note.id)
    return true
  })
}

function makeEmptyNotesInfiniteData(): NotesInfiniteData {
  return { pages: [{ items: [], nextOffset: null }], pageParams: [0] }
}

export function normalizeNotesQueryData(data: NotesQueryData): NotesInfiniteData | undefined {
  if (!data) return undefined
  if (Array.isArray(data)) {
    return { pages: [{ items: data, nextOffset: null }], pageParams: [0] }
  }
  if (Array.isArray(data.pages) && Array.isArray(data.pageParams)) return data
  return undefined
}

function ensureNotesInfiniteData(data: NotesQueryData): NotesInfiniteData {
  const normalized = normalizeNotesQueryData(data) ?? makeEmptyNotesInfiniteData()
  if (normalized.pages.length > 0) return normalized
  return makeEmptyNotesInfiniteData()
}

export function upsertNoteInNotesQueryData(data: NotesQueryData, note: Note): NotesInfiniteData {
  const normalized = ensureNotesInfiniteData(data)
  return {
    ...normalized,
    pages: normalized.pages.map((page, index) => {
      const items = page.items ?? []
      const filteredItems = items.filter(item => item.id !== note.id)
      return {
        ...page,
        items: index === 0 ? [note, ...filteredItems] : filteredItems,
      }
    }),
  }
}

export function removeNotesFromNotesQueryData(
  data: NotesQueryData,
  slugs: Iterable<string>,
): NotesInfiniteData | undefined {
  const normalized = normalizeNotesQueryData(data)
  if (!normalized) return undefined
  const slugSet = new Set(slugs)
  return {
    ...normalized,
    pages: normalized.pages.map(page => ({
      ...page,
      items: (page.items ?? []).filter(note => !slugSet.has(note.slug)),
    })),
  }
}

export function replaceNoteInNotesQueryData(
  data: NotesQueryData,
  updatedNote: Note,
): NotesInfiniteData | undefined {
  const normalized = normalizeNotesQueryData(data)
  if (!normalized) return undefined
  return {
    ...normalized,
    pages: normalized.pages.map(page => ({
      ...page,
      items: (page.items ?? []).map(note => (
        note.id === updatedNote.id || note.slug === updatedNote.slug ? updatedNote : note
      )),
    })),
  }
}

export function mergeNoteInNotesQueryData(
  data: NotesQueryData,
  mergedNote: Note,
  sourceSlug: string,
): NotesInfiniteData | undefined {
  const normalized = normalizeNotesQueryData(data)
  if (!normalized) return undefined
  return {
    ...normalized,
    pages: normalized.pages.map(page => ({
      ...page,
      items: (page.items ?? [])
        .filter(note => note.slug !== sourceSlug)
        .map(note => note.slug === mergedNote.slug ? mergedNote : note),
    })),
  }
}

export function useNotes(params: NotesParams = {}) {
  const hasSearchOrFilters = hasNotesSearchOrFilters(params)
  const queryClient = useQueryClient()
  const queryKey = notesQueryKey(params)
  const stableParams = queryKey[1]
  const stableParamsKey = JSON.stringify(stableParams)
  const refreshInFlightRef = useRef(false)
  const query = useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam, signal }) => fetchNotesPage(params, signal, {
      limit: NOTES_PAGE_SIZE,
      offset: pageParam,
    }),
    initialPageParam: 0,
    getNextPageParam: page => page.nextOffset ?? undefined,
    staleTime: hasSearchOrFilters ? 5_000 : 10_000,
    placeholderData: previousData => previousData,
    refetchOnWindowFocus: hasSearchOrFilters ? 'always' : false,
  })

  useEffect(() => {
    if (typeof window === 'undefined' || typeof document === 'undefined') return

    const queryParams = JSON.parse(stableParamsKey) as NotesQueryParams
    const interval = notesRefetchInterval(queryParams, document.visibilityState)
    if (interval === false) return

    const pollParams = notesParamsFromQueryParams(queryParams)
    const pollQueryKey = notesQueryKey(pollParams)
    let cancelled = false

    async function refreshFirstPage() {
      if (document.visibilityState !== 'visible' || refreshInFlightRef.current) return
      refreshInFlightRef.current = true
      try {
        const firstPage = await fetchNotesPage(pollParams, undefined, {
          limit: NOTES_PAGE_SIZE,
          offset: 0,
        })
        if (cancelled) return
        queryClient.setQueryData<NotesQueryData>(
          pollQueryKey,
          current => {
            const normalized = normalizeNotesQueryData(current)
            if (!normalized) return { pages: [firstPage], pageParams: [0] }
            return {
              ...normalized,
              pages: [firstPage, ...normalized.pages.slice(1)],
              pageParams: [0, ...normalized.pageParams.slice(1)],
            }
          },
        )
      } finally {
        refreshInFlightRef.current = false
      }
    }

    const intervalId = window.setInterval(() => {
      void refreshFirstPage()
    }, interval)
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') void refreshFirstPage()
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      cancelled = true
      window.clearInterval(intervalId)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [queryClient, stableParamsKey])

  return {
    ...query,
    data: query.data ? dedupeNotes(query.data.pages.flatMap(page => page.items)) : undefined,
  }
}
