import { type InfiniteData, useInfiniteQuery } from '@tanstack/react-query'
import { fetchNotesPage, NOTES_PAGE_SIZE } from '../api/notes.ts'
import type { Note, NotesPageResult, NotesParams } from '../types/index.ts'

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

export type NotesInfiniteData = InfiniteData<NotesPageResult, number>
export type NotesQueryData = NotesInfiniteData | Note[] | undefined

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

/**
 * Applies a change-feed batch to one cached list: known cards are replaced in place (keeping
 * list-specific fields such as search matches and the client's stable key), removed ids are
 * dropped, and — only for the unfiltered list — unknown cards are prepended. Returns the same
 * object when nothing changed so React Query skips re-rendering.
 */
export function applyNoteChangesToNotesQueryData(
  data: NotesQueryData,
  changed: ReadonlyMap<string, Note>,
  removedIds: ReadonlySet<string>,
  options: { insertNew: boolean },
): NotesQueryData {
  const normalized = normalizeNotesQueryData(data)
  if (!normalized) return data
  const seen = new Set<string>()
  let modified = false
  const pages = normalized.pages.map((page) => {
    let pageModified = false
    const items: Note[] = []
    for (const note of page.items ?? []) {
      if (removedIds.has(note.id)) {
        pageModified = true
        continue
      }
      const update = changed.get(note.id)
      seen.add(note.id)
      if (update) {
        pageModified = true
        items.push({
          ...update,
          searchMatches: note.searchMatches?.length ? note.searchMatches : update.searchMatches,
          stableKey: note.stableKey,
        })
      } else {
        items.push(note)
      }
    }
    if (!pageModified) return page
    modified = true
    return { ...page, items }
  })
  if (options.insertNew) {
    const fresh = [...changed.values()].filter(note => !seen.has(note.id) && !removedIds.has(note.id))
    if (fresh.length) {
      modified = true
      pages[0] = { ...pages[0], items: [...fresh, ...(pages[0]?.items ?? [])] }
    }
  }
  return modified ? { ...normalized, pages } : data
}

/**
 * Paginated note cards. Freshness comes from the change feed (`useNotesChangeFeed`), which
 * merges updated cards into these caches, so lists are never re-polled.
 */
export function useNotes(params: NotesParams = {}) {
  const query = useInfiniteQuery({
    queryKey: notesQueryKey(params),
    queryFn: ({ pageParam, signal }) => fetchNotesPage(params, signal, {
      limit: NOTES_PAGE_SIZE,
      offset: pageParam,
    }),
    initialPageParam: 0,
    getNextPageParam: page => page.nextOffset ?? undefined,
    placeholderData: previousData => previousData,
  })

  return {
    ...query,
    data: query.data ? dedupeNotes(query.data.pages.flatMap(page => page.items)) : undefined,
  }
}
