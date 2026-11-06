import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type RefObject } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { Note } from '../../types'
import { reorderNotes } from '../../api/notes'
import { NoteCard } from '../NoteCard/NoteCard'
import { AddNoteCard } from '../NoteCard/AddNoteCard'
import { NoteCardActionsProvider } from '../NoteCard/NoteCardActions'
import { DragProvider } from '../../contexts/DragContext'
import { useSettings } from '../../contexts/SettingsContext'
import { useMediaQuery } from '../../hooks/useMediaQuery'
import { LoaderSpinner } from '../LoaderSpinner'
import { calculateMasonryGridMetrics, orderNotesByIds, toReorderPayload } from '../../utils/noteGridOrder'
import { useGridMetrics } from './useGridMetrics'
import { useMuuriLayout } from './useMuuriLayout'
import styles from './NoteGrid.module.css'

const MOBILE_GRID_QUERY = '(max-width: 760px), (pointer: coarse)'
const LOAD_MORE_MARGIN_PX = 520
const ITEM_CLASSES = {
  dragging: styles.itemDragging,
  releasing: styles.itemReleasing,
  hidden: styles.itemHidden,
  positioning: styles.itemPositioning,
}

interface NoteGridProps {
  notes: Note[]
  preserveOrder?: boolean
  showAddCard?: boolean
  isUpdating?: boolean
  updatingLabel?: string
  emptyState?: {
    title: string
    description: string
  }
  onAddNote?: () => void
  onTagClick?: (tag: string) => void
  hasMore?: boolean
  isLoadingMore?: boolean
  onLoadMore?: () => void
}

function noteKey(note: Note): string {
  return note.stableKey ?? note.id
}

/**
 * Keeps the user's on-screen order: notes already shown stay where they are (with fresh data),
 * new notes go to the front. Returns `current` itself when nothing changed so React and Muuri
 * can skip the update entirely.
 */
function mergePreservingOrder(current: Note[], incoming: Note[]): Note[] {
  if (current.length === 0) return incoming
  const byId = new Map<string, Note>()
  for (const note of incoming) {
    byId.set(note.id, note)
    if (note.stableKey) byId.set(note.stableKey, note)
  }
  const kept: Note[] = []
  const keptNotes = new Set<Note>()
  for (const note of current) {
    const fresh = byId.get(note.id) ?? (note.stableKey ? byId.get(note.stableKey) : undefined)
    if (fresh && !keptNotes.has(fresh)) {
      kept.push(fresh)
      keptNotes.add(fresh)
    }
  }
  const added = incoming.filter(note => !keptNotes.has(note))
  const next = added.length > 0 ? [...added, ...kept] : kept
  return next.length === current.length && next.every((note, index) => note === current[index]) ? current : next
}

function sameOrder(a: readonly Note[], b: readonly Note[]): boolean {
  return a.length === b.length && a.every((note, index) => note.id === b[index]?.id)
}

/** Calls the latest callback without changing identity (keeps memoized children/effects stable). */
function useStableCallback<Args extends unknown[]>(callback: ((...args: Args) => void) | undefined) {
  const ref = useRef(callback)
  useLayoutEffect(() => {
    ref.current = callback
  })
  return useCallback((...args: Args) => ref.current?.(...args), [])
}

function useLoadMoreSentinel(
  scrollRef: RefObject<HTMLDivElement | null>,
  sentinelRef: RefObject<HTMLDivElement | null>,
  enabled: boolean,
  onLoadMore: () => void,
) {
  useEffect(() => {
    const scrollArea = scrollRef.current
    const sentinel = sentinelRef.current
    if (!scrollArea || !sentinel || !enabled) return
    let requested = false
    const request = () => {
      if (requested) return
      requested = true
      onLoadMore()
    }

    if (typeof IntersectionObserver === 'undefined') {
      const handleScroll = () => {
        if (scrollArea.scrollHeight - scrollArea.scrollTop - scrollArea.clientHeight < LOAD_MORE_MARGIN_PX) request()
      }
      handleScroll()
      scrollArea.addEventListener('scroll', handleScroll, { passive: true })
      return () => scrollArea.removeEventListener('scroll', handleScroll)
    }

    const observer = new IntersectionObserver(
      entries => {
        if (entries.some(entry => entry.isIntersecting)) request()
      },
      { root: scrollArea, rootMargin: `${LOAD_MORE_MARGIN_PX}px 0px`, threshold: 0 },
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [scrollRef, sentinelRef, enabled, onLoadMore])
}

export function NoteGrid({
  notes,
  preserveOrder = true,
  showAddCard = true,
  isUpdating = false,
  updatingLabel = 'Обновляем заметки',
  emptyState,
  onAddNote,
  onTagClick,
  hasMore = false,
  isLoadingMore = false,
  onLoadMore,
}: NoteGridProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const gridRef = useRef<HTMLDivElement>(null)
  const loadMoreRef = useRef<HTMLDivElement>(null)
  const queryClient = useQueryClient()
  const { cols } = useSettings()
  const isMobileGrid = useMediaQuery(MOBILE_GRID_QUERY)
  const metrics = useGridMetrics(scrollRef, cols)

  const [orderedNotes, setOrderedNotes] = useState<Note[]>(notes)
  const orderedNotesRef = useRef(orderedNotes)
  const dragStartOrderRef = useRef<Note[] | null>(null)
  const pendingNotesRef = useRef<Note[] | null>(null)
  const isDraggingRef = useRef(false)

  const applyNotes = useCallback((next: Note[]) => {
    orderedNotesRef.current = next
    setOrderedNotes(next)
  }, [])

  const mergeIncoming = useCallback((incoming: Note[]) => {
    applyNotes(preserveOrder ? mergePreservingOrder(orderedNotesRef.current, incoming) : incoming)
  }, [applyNotes, preserveOrder])

  useEffect(() => {
    if (isDraggingRef.current) {
      pendingNotesRef.current = notes
      return
    }
    mergeIncoming(notes)
  }, [notes, mergeIncoming])

  const layoutKey = useMemo(() => orderedNotes.map(noteKey).join('|'), [orderedNotes])

  const persistOrder = useCallback((next: Note[], previous: Note[] | null) => {
    const persisted = next.filter(note => !note.isLocal && !note.isLoading)
    if (persisted.length === 0) return
    reorderNotes(toReorderPayload(persisted))
      .catch(error => {
        console.error('Failed to save note order', error)
        if (previous) applyNotes(previous)
      })
      .finally(() => queryClient.invalidateQueries({ queryKey: ['notes'] }))
  }, [applyNotes, queryClient])

  const { isReady, handleClickCapture } = useMuuriLayout({
    gridRef,
    scrollRef,
    metrics,
    dragEnabled: !isMobileGrid,
    itemClassName: styles.item,
    itemClasses: ITEM_CLASSES,
    layoutKey,
    onDragStart: () => {
      isDraggingRef.current = true
      dragStartOrderRef.current = orderedNotesRef.current
    },
    onDragEnd: orderedIds => {
      const previous = dragStartOrderRef.current
      dragStartOrderRef.current = null
      const next = orderNotesByIds(orderedNotesRef.current, orderedIds)
      if (sameOrder(orderedNotesRef.current, next)) return
      applyNotes(next)
      persistOrder(next, previous)
    },
    onDragSettled: () => {
      isDraggingRef.current = false
      const pending = pendingNotesRef.current
      pendingNotesRef.current = null
      if (pending) mergeIncoming(pending)
    },
  })

  const stableTagClick = useStableCallback(onTagClick)
  const stableLoadMore = useStableCallback(onLoadMore)
  useLoadMoreSentinel(scrollRef, loadMoreRef, hasMore && !isLoadingMore && Boolean(onLoadMore), stableLoadMore)

  const visibleMetrics = metrics ?? calculateMasonryGridMetrics(0, cols)
  const gridStyle = {
    '--note-grid-content-width': `${visibleMetrics.contentWidth}px`,
    '--note-grid-item-width': `${visibleMetrics.itemWidth}px`,
    '--note-grid-cols': visibleMetrics.cols,
  } as CSSProperties
  const itemStyle = metrics ? { width: `${metrics.itemWidth}px` } : undefined

  return (
    <DragProvider>
      <NoteCardActionsProvider>
        <div ref={scrollRef} className={styles.scrollArea}>
          {!isReady && (
            <div className={styles.gridBootLoader} role="status" aria-label="Загрузка заметок">
              <LoaderSpinner size="md" />
            </div>
          )}
          {isUpdating && isReady && (
            <div className={styles.updateStatus} role="status" aria-live="polite">
              <LoaderSpinner size="xs" />
              <span>{updatingLabel}</span>
            </div>
          )}
          <div
            ref={gridRef}
            className={[styles.grid, isMobileGrid ? styles.mobileGrid : '', isUpdating ? styles.gridUpdating : ''].filter(Boolean).join(' ')}
            style={gridStyle}
            onClickCapture={handleClickCapture}
            aria-busy={isUpdating ? 'true' : undefined}
            data-grid-measured={metrics ? 'true' : undefined}
            data-masonry-bootstrapping={isReady ? undefined : 'true'}
            data-masonry-ready={isReady ? 'true' : undefined}
            data-mobile-grid={isMobileGrid ? 'true' : undefined}
            data-mobile-cols={isMobileGrid ? String(visibleMetrics.cols) : undefined}
          >
            {showAddCard && (
              <div className={`${styles.item} ${styles.addItem}`} style={itemStyle} data-static-item="true">
                <div className={styles.itemContent}>
                  <AddNoteCard onClick={onAddNote} />
                </div>
              </div>
            )}

            {orderedNotes.length === 0 && emptyState ? (
              <div className={`${styles.item} ${styles.emptyItem}`} style={itemStyle} data-static-item="true">
                <div className={styles.emptyState}>
                  <h2>{emptyState.title}</h2>
                  <p>{emptyState.description}</p>
                </div>
              </div>
            ) : null}

            {orderedNotes.map(note => (
              <div
                key={noteKey(note)}
                className={styles.item}
                data-note-id={note.id}
                data-note-slug={note.slug}
                data-drag-disabled={note.isLocal || note.isLoading || isMobileGrid ? 'true' : undefined}
                style={itemStyle}
              >
                <div className={styles.itemContent}>
                  <NoteCard note={note} onTagClick={stableTagClick} />
                </div>
              </div>
            ))}
          </div>
          {hasMore && <div ref={loadMoreRef} className={styles.loadMoreSentinel} aria-hidden="true" />}
        </div>
      </NoteCardActionsProvider>
    </DragProvider>
  )
}
