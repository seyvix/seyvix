import { useEffect, useRef } from 'react'
import { type QueryClient, useQueryClient } from '@tanstack/react-query'
import { fetchNoteChanges } from '../api/notes.ts'
import type { Note, NotesChangesResult, NotesParams } from '../types/index.ts'
import {
  applyNoteChangesToNotesQueryData,
  hasNotesSearchOrFilters,
  normalizeNotesQueryData,
  type NotesQueryData,
} from './useNotes.ts'

/**
 * Keeps every note cache fresh from `GET /api/v1/notes/changes?since=<cursor>`.
 *
 * Cadence: every 5 s while a note on screen is `processing`, every 30 s otherwise; paused while
 * the tab is hidden, immediate when it becomes visible again or the network comes back;
 * exponential backoff on errors. Mount exactly once (AppLayout).
 */

const FAST_POLL_MS = 5_000
const IDLE_POLL_MS = 30_000
const MAX_BACKOFF_MS = 5 * 60_000

/** Per-note detail queries (keyed by note id or slug) refreshed when that note changes. */
const PER_NOTE_QUERY_ROOTS = [
  'note',
  'content-tags',
  'content-tag-suggestions',
  'content-tag-jobs',
  'taxonomy-assignments',
  'taxonomy-classification-jobs',
  'snapshot-jobs',
  'snapshot-artifacts',
] as const

/** Everything derived from note data; refetched when the server says our cursor is unusable. */
const NOTE_DATA_ROOTS = new Set<unknown>([...PER_NOTE_QUERY_ROOTS, 'notes', 'notes-trash', 'folders', 'category'])

export interface NoteChangeBatch {
  notes: Note[]
  removedIds: string[]
  reset: boolean
}

type NoteChangeListener = (batch: NoteChangeBatch) => void

const listeners = new Set<NoteChangeListener>()
let requestSync: (() => void) | null = null

/** Observe every applied change batch. Returns an unsubscribe function. */
export function subscribeToNoteChanges(listener: NoteChangeListener): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function useNoteChangeListener(listener: NoteChangeListener): void {
  const latest = useRef(listener)
  latest.current = listener
  useEffect(() => subscribeToNoteChanges(batch => latest.current(batch)), [])
}

/** Poll now (e.g. right after an action that starts server-side processing). */
export function requestChangeFeedSync(): void {
  requestSync?.()
}

/** True when a mounted list or detail view shows a note the server is still processing. */
export function hasVisibleProcessingNotes(queryClient: QueryClient): boolean {
  const cache = queryClient.getQueryCache()
  for (const query of cache.findAll({ queryKey: ['notes'], type: 'active' })) {
    const data = normalizeNotesQueryData(query.state.data as NotesQueryData)
    if (data?.pages.some(page => page.items?.some(note => note.processing))) return true
  }
  return cache
    .findAll({ queryKey: ['note'], type: 'active' })
    .some(query => (query.state.data as Note | undefined)?.processing === true)
}

/**
 * Merges one change batch into the query cache. `requestStartedAt` is when the feed request
 * was sent: on `reset`, only data loaded before that moment can be older than the new cursor.
 */
export function applyNoteChanges(
  queryClient: QueryClient,
  batch: NotesChangesResult,
  requestStartedAt: number,
): void {
  if (batch.reset) {
    void queryClient.invalidateQueries({
      predicate: query => NOTE_DATA_ROOTS.has(query.queryKey[0]) && query.state.dataUpdatedAt < requestStartedAt,
    })
    return
  }
  if (batch.notes.length === 0 && batch.removedIds.length === 0) return

  const changed = new Map(batch.notes.map(note => [note.id, note]))
  const removed = new Set(batch.removedIds)
  const cache = queryClient.getQueryCache()
  const listQueries = cache.findAll({ queryKey: ['notes'] })

  // Category counts only move when a note appears, disappears or changes category.
  const previous = new Map<string, Note>()
  for (const query of listQueries) {
    for (const page of normalizeNotesQueryData(query.state.data as NotesQueryData)?.pages ?? []) {
      for (const note of page.items ?? []) if (changed.has(note.id)) previous.set(note.id, note)
    }
  }
  const categoriesChanged = removed.size > 0 || batch.notes.some(note => (
    previous.get(note.id)?.taxonomyCategory?.id !== note.taxonomyCategory?.id || !previous.has(note.id)
  ))

  for (const query of listQueries) {
    const params = query.queryKey[1] as NotesParams | undefined
    queryClient.setQueryData<NotesQueryData>(query.queryKey, data => applyNoteChangesToNotesQueryData(
      data,
      changed,
      removed,
      // Only the unfiltered feed can safely show notes it hasn't seen; filtered/search
      // results would need the server to decide whether a new note matches.
      { insertNew: !hasNotesSearchOrFilters(params) },
    ))
  }

  const refs = new Set<string>(batch.removedIds)
  for (const note of batch.notes) {
    refs.add(note.id)
    refs.add(note.slug)
  }
  void queryClient.invalidateQueries({
    predicate: ({ queryKey }) => (
      (PER_NOTE_QUERY_ROOTS as readonly unknown[]).includes(queryKey[0])
      && refs.has(String(queryKey[1]))
    ),
  })
  if (removed.size > 0) void queryClient.invalidateQueries({ queryKey: ['notes-trash'] })
  if (categoriesChanged) {
    void queryClient.invalidateQueries({ queryKey: ['folders'] })
    void queryClient.invalidateQueries({ queryKey: ['category'] })
  }
}

export function useNotesChangeFeed(): void {
  const queryClient = useQueryClient()

  useEffect(() => {
    let cursor: string | null = null
    let timer: number | undefined
    let scheduledDelay = 0
    let controller: AbortController | null = null
    let running = false
    let failures = 0
    let disposed = false

    const schedule = (delay: number) => {
      window.clearTimeout(timer)
      scheduledDelay = delay
      if (disposed || document.visibilityState === 'hidden') return
      timer = window.setTimeout(() => void poll(), delay)
    }

    const nextDelay = () => {
      if (failures > 0) return Math.min(IDLE_POLL_MS * 2 ** (failures - 1), MAX_BACKOFF_MS)
      return hasVisibleProcessingNotes(queryClient) ? FAST_POLL_MS : IDLE_POLL_MS
    }

    async function poll() {
      if (running || disposed || document.visibilityState === 'hidden') return
      running = true
      window.clearTimeout(timer)
      controller = new AbortController()
      try {
        let more = true
        while (more && !disposed) {
          const startedAt = Date.now()
          const batch = await fetchNoteChanges(cursor, controller.signal)
          applyNoteChanges(queryClient, batch, startedAt)
          cursor = batch.cursor
          more = batch.hasMore && !batch.reset
          for (const listener of listeners) listener(batch)
        }
        failures = 0
      } catch (error) {
        if (!controller.signal.aborted) {
          failures += 1
          console.warn('[change-feed] poll failed', error)
        }
      } finally {
        running = false
        controller = null
        if (!disposed) schedule(nextDelay())
      }
    }

    const handleVisibility = () => {
      if (document.visibilityState === 'visible') void poll()
      else window.clearTimeout(timer)
    }
    const handleOnline = () => {
      failures = 0
      void poll()
    }
    // Switch to the fast cadence as soon as a processing note shows up (e.g. after an upload).
    const unsubscribeCache = queryClient.getQueryCache().subscribe((event) => {
      if (running || failures > 0 || scheduledDelay <= FAST_POLL_MS) return
      if (event.type !== 'updated' || event.action.type !== 'success') return
      const root = event.query.queryKey[0]
      if ((root === 'notes' || root === 'note') && hasVisibleProcessingNotes(queryClient)) schedule(FAST_POLL_MS)
    })

    document.addEventListener('visibilitychange', handleVisibility)
    window.addEventListener('online', handleOnline)
    requestSync = () => void poll()
    void poll()

    return () => {
      disposed = true
      window.clearTimeout(timer)
      controller?.abort()
      unsubscribeCache()
      document.removeEventListener('visibilitychange', handleVisibility)
      window.removeEventListener('online', handleOnline)
      requestSync = null
    }
  }, [queryClient])
}
