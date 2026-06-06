import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react'
import { flushSync } from 'react-dom'
import { useQueryClient } from '@tanstack/react-query'
import type { Note } from '../../types'
import { reorderNotes } from '../../api/notes'
import { NoteCard, AddNoteCard } from '../NoteCard/NoteCard'
import { DragProvider } from '../../contexts/DragContext'
import { useSettings } from '../../contexts/SettingsContext'
import {
  buildMasonryLayoutSlots,
  calculateMasonryGridMetrics,
  orderNotesByIds,
  toReorderPayload,
  type MasonryGridMetrics,
} from '../../utils/noteGridOrder'
import styles from './NoteGrid.module.css'

const GRID_GAP = 8
const MOBILE_GRID_QUERY = '(max-width: 760px), (pointer: coarse)'

type MuuriGrid = InstanceType<(typeof import('muuri'))['default']>
type MuuriItem = import('muuri').Item

interface NoteGridProps {
  notes: Note[]
  onAddNote?: () => void
  onTagClick?: (tag: string) => void
}

export function NoteGrid({ notes, onAddNote, onTagClick }: NoteGridProps) {
  const knownKeysRef  = useRef(new Set<string>())
  const isFirstRender = useRef(true)
  const scrollRef = useRef<HTMLDivElement>(null)
  const gridRef = useRef<HTMLDivElement>(null)
  const muuriRef = useRef<MuuriGrid | null>(null)
  const itemResizeObserverRef = useRef<ResizeObserver | null>(null)
  const dragStartOrderRef = useRef<Note[] | null>(null)
  const isDraggingRef = useRef(false)
  const pendingNotesRef = useRef<Note[] | null>(null)
  const orderedNotesRef = useRef<Note[]>(notes)
  const gridMetricsRef = useRef<MasonryGridMetrics | null>(null)
  const [orderedNotes, setOrderedNotes] = useState<Note[]>(notes)
  const [gridMetrics, setGridMetrics] = useState<MasonryGridMetrics | null>(null)
  const [isMobileGrid, setIsMobileGrid] = useState(() => (
    typeof window !== 'undefined' &&
    typeof window.matchMedia !== 'undefined' &&
    window.matchMedia(MOBILE_GRID_QUERY).matches
  ))
  const queryClient = useQueryClient()
  const { cols } = useSettings()
  const hasGridMetrics = gridMetrics !== null

  gridMetricsRef.current = gridMetrics

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia === 'undefined') return
    const media = window.matchMedia(MOBILE_GRID_QUERY)
    const handleChange = () => setIsMobileGrid(media.matches)

    handleChange()
    media.addEventListener?.('change', handleChange)
    return () => media.removeEventListener?.('change', handleChange)
  }, [])

  function mergeIncomingNotes(incomingNotes: Note[]) {
    setOrderedNotes(current => {
      if (current.length === 0) {
        orderedNotesRef.current = incomingNotes
        return incomingNotes
      }

      const incomingById = new Map(incomingNotes.map(note => [note.id, note]))
      const currentIds = new Set(current.map(note => note.id))
      const added = incomingNotes.filter(note => !currentIds.has(note.id))
      const kept = current
        .map(note => incomingById.get(note.id))
        .filter((note): note is Note => Boolean(note))
      const next = [...added, ...kept]

      orderedNotesRef.current = next
      return next
    })
  }

  useEffect(() => {
    if (isDraggingRef.current) {
      pendingNotesRef.current = notes
      return
    }

    mergeIncomingNotes(notes)
  }, [notes])

  useEffect(() => {
    orderedNotesRef.current = orderedNotes
  }, [orderedNotes])

  useLayoutEffect(() => {
    const scrollArea = scrollRef.current
    if (!scrollArea) return

    function updateGridMetrics(width: number) {
      setGridMetrics(calculateMasonryGridMetrics(width, cols))
    }

    updateGridMetrics(scrollArea.clientWidth)

    if (typeof ResizeObserver === 'undefined') {
      const handleResize = () => updateGridMetrics(scrollArea.clientWidth)
      window.addEventListener('resize', handleResize)
      return () => window.removeEventListener('resize', handleResize)
    }

    const observer = new ResizeObserver(entries => {
      const entry = entries[0]
      if (entry) updateGridMetrics(entry.contentRect.width)
    })
    observer.observe(scrollArea)
    return () => observer.disconnect()
  }, [cols])

  useLayoutEffect(() => {
    const gridElement = gridRef.current
    const initialMetrics = gridMetricsRef.current
    if (!gridElement || !initialMetrics) return

    let disposed = false
    let cleanup: (() => void) | null = null

    void import('muuri').then(({ default: Muuri }) => {
      if (disposed) return

      const grid = new Muuri(gridElement, {
        items: `.${styles.item}`,
        layout: (_grid, id, items, _width, _height, callback) => {
          const metrics = gridMetricsRef.current ?? initialMetrics
          const layout = buildMasonryLayoutSlots({
            heights: items.map(item => item.getHeight()),
            cols: metrics.cols,
            itemWidth: metrics.itemWidth,
            gap: GRID_GAP,
          })

          callback({
            id,
            items,
            slots: layout.slots,
            styles: {
              height: `${layout.height}px`,
            },
          })
        },
        layoutOnResize: 80,
        layoutDuration: 180,
        layoutEasing: 'ease',
        dragEnabled: !isMobileGrid,
        dragContainer: document.body,
        dragStartPredicate: (item, event) => {
          if (isMobileGrid) return false
          const element = item.getElement()
          if (!element || element.dataset.staticItem === 'true' || element.dataset.dragDisabled === 'true') {
            return false
          }

          return Muuri.ItemDrag.defaultStartPredicate(item, event, { distance: 6 })
        },
        dragSort: true,
        dragSortHeuristics: {
          sortInterval: 60,
          minDragDistance: 8,
          minBounceBackAngle: 1,
        },
        dragSortPredicate: {
          threshold: 65,
          action: 'swap',
          migrateAction: 'swap',
        },
        dragRelease: {
          duration: 180,
          easing: 'ease',
          useDragContainer: true,
        },
        dragAutoScroll: {
          targets: () => {
            const scrollArea = scrollRef.current
            return scrollArea ? [scrollArea] : []
          },
        },
        itemClass: styles.item,
        itemDraggingClass: styles.itemDragging,
        itemReleasingClass: styles.itemReleasing,
        itemHiddenClass: styles.itemHidden,
        itemPositioningClass: styles.itemPositioning,
      })

      if (disposed) {
        grid.destroy(false)
        return
      }

      muuriRef.current = grid

      if (typeof ResizeObserver !== 'undefined') {
        itemResizeObserverRef.current = new ResizeObserver(() => {
          if (isDraggingRef.current) return
          window.requestAnimationFrame(() => {
            if (!isDraggingRef.current && muuriRef.current === grid) grid.refreshItems().layout()
          })
        })
      }

      const handleDragStart = () => {
        isDraggingRef.current = true
        dragStartOrderRef.current = orderedNotesRef.current
      }

      const handleDragReleaseEnd = () => {
        const previous = dragStartOrderRef.current
        dragStartOrderRef.current = null
        const nextIds = getNoteIdsFromGrid(grid)
        const next = orderNotesByIds(orderedNotesRef.current, nextIds)
        const finishDrag = () => {
          window.requestAnimationFrame(() => {
            isDraggingRef.current = false
            const pendingNotes = pendingNotesRef.current
            pendingNotesRef.current = null
            if (pendingNotes) mergeIncomingNotes(pendingNotes)
            if (muuriRef.current === grid) grid.refreshItems().layout()
          })
        }

        if (sameNoteOrder(orderedNotesRef.current, next)) {
          finishDrag()
          return
        }

        orderedNotesRef.current = next
        flushSync(() => setOrderedNotes(next))

        const persisted = next.filter(note => !note.isLocal && !note.isLoading)
        if (persisted.length === 0) {
          finishDrag()
          return
        }

        void reorderNotes(toReorderPayload(persisted))
          .then(() => queryClient.invalidateQueries({ queryKey: ['notes'] }))
          .catch(() => {
            if (previous) {
              orderedNotesRef.current = previous
              setOrderedNotes(previous)
            }
            void queryClient.invalidateQueries({ queryKey: ['notes'] })
          })

        finishDrag()
      }

      grid.on('dragStart', handleDragStart)
      grid.on('dragReleaseEnd', handleDragReleaseEnd)

      cleanup = () => {
        grid.off('dragStart', handleDragStart)
        grid.off('dragReleaseEnd', handleDragReleaseEnd)
        itemResizeObserverRef.current?.disconnect()
        itemResizeObserverRef.current = null
        grid.destroy(false)
        if (muuriRef.current === grid) muuriRef.current = null
      }
    })

    return () => {
      disposed = true
      cleanup?.()
    }
  }, [hasGridMetrics, isMobileGrid, queryClient])

  useLayoutEffect(() => {
    const grid = muuriRef.current
    const gridElement = gridRef.current
    if (!grid || !gridElement || !gridMetrics) return
    if (isDraggingRef.current) return

    syncMuuriItems(grid, gridElement)
    observeMuuriItems(itemResizeObserverRef.current, gridElement)
    grid.refreshItems(undefined, true).synchronize().layout()
  }, [orderedNotes, gridMetrics])

  if (isFirstRender.current) {
    isFirstRender.current = false
    notes.forEach(n => knownKeysRef.current.add(n.stableKey ?? n.id))
  }

  const visibleMetrics = gridMetrics ?? calculateMasonryGridMetrics(0, cols)
  const gridStyle = {
    '--note-grid-content-width': `${visibleMetrics.contentWidth}px`,
    '--note-grid-item-width': `${visibleMetrics.itemWidth}px`,
  } as CSSProperties
  const itemStyle = { width: `${visibleMetrics.itemWidth}px` } as CSSProperties

  return (
    <DragProvider>
      <div ref={scrollRef} className={styles.scrollArea}>
        <div
          ref={gridRef}
          className={`${styles.grid} ${isMobileGrid ? styles.mobileGrid : ''}`}
          style={gridStyle}
          data-mobile-grid={isMobileGrid ? 'true' : undefined}
        >
          <div className={`${styles.item} ${styles.addItem}`} style={itemStyle} data-static-item="true" data-muuri-item>
            <div className={styles.itemContent}>
              <AddNoteCard onClick={onAddNote} />
            </div>
          </div>

          {orderedNotes.map(note => {
            const key = note.stableKey ?? note.id
            const isNew = !knownKeysRef.current.has(key)
            knownKeysRef.current.add(key)

            return (
              <div
                key={key}
                className={styles.item}
                data-note-id={note.id}
                data-note-slug={note.slug}
                data-drag-disabled={note.isLocal || note.isLoading || isMobileGrid ? 'true' : undefined}
                data-muuri-item
                style={itemStyle}
              >
                <div className={styles.itemContent}>
                  <NoteCard note={note} isNew={isNew} onTagClick={onTagClick} />
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </DragProvider>
  )
}

function getNoteIdsFromGrid(grid: MuuriGrid): string[] {
  return grid
    .getItems()
    .map(item => item.getElement()?.dataset.noteId)
    .filter((id): id is string => Boolean(id))
}

function sameNoteOrder(a: readonly Note[], b: readonly Note[]): boolean {
  return a.length === b.length && a.every((note, index) => note.id === b[index]?.id)
}

function syncMuuriItems(grid: MuuriGrid, gridElement: HTMLElement) {
  const muuriItems = grid.getItems()
  const knownElements = new Set(muuriItems.map(item => item.getElement()).filter((element): element is HTMLElement => Boolean(element)))
  const domItems = Array.from(gridElement.children).filter((element): element is HTMLElement => (
    element instanceof HTMLElement && element.classList.contains(styles.item)
  ))
  const domItemSet = new Set(domItems)
  const removedItems = muuriItems.filter(item => {
    const element = item.getElement()
    return !element || !domItemSet.has(element)
  })
  const addedElements = domItems.filter(element => !knownElements.has(element))

  if (removedItems.length > 0) {
    grid.remove(removedItems as MuuriItem[], { removeElements: false, layout: false })
  }

  if (addedElements.length > 0) {
    grid.add(addedElements, { layout: false })
  }

  const orderedItems = domItems
    .map(element => grid.getItem(element))
    .filter((item): item is MuuriItem => Boolean(item))

  if (orderedItems.length === grid.getItems().length) {
    grid.sort(orderedItems, { layout: false })
  }
}

function observeMuuriItems(observer: ResizeObserver | null, gridElement: HTMLElement) {
  if (!observer) return
  observer.disconnect()
  Array.from(gridElement.children).forEach(element => {
    if (element instanceof HTMLElement && element.classList.contains(styles.item)) {
      observer.observe(element)
    }
  })
}
