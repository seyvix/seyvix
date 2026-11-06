import { useCallback, useEffect, useLayoutEffect, useRef, useState, type MouseEvent, type RefObject } from 'react'
import { flushSync } from 'react-dom'
import type MuuriGrid from 'muuri'
import type { Item as MuuriItem } from 'muuri'
import { buildMasonryLayoutSlots, type MasonryGridMetrics } from '../../utils/noteGridOrder'

export const GRID_GAP = 8
const DRAG_CLICK_SUPPRESSION_MS = 350

interface MuuriLayoutOptions {
  gridRef: RefObject<HTMLDivElement | null>
  scrollRef: RefObject<HTMLDivElement | null>
  metrics: MasonryGridMetrics | null
  dragEnabled: boolean
  /** CSS class marking grid items (Muuri items are the grid's direct children with it). */
  itemClassName: string
  itemClasses: { dragging: string; releasing: string; hidden: string; positioning: string }
  /** Changes whenever the set/order of rendered items changes; content changes are picked up by ResizeObserver. */
  layoutKey: string
  onDragStart: () => void
  /** Called with the DOM order of note ids after a drag finished. */
  onDragEnd: (orderedIds: string[]) => void
  /** Called once the release animation settled and layout may change again. */
  onDragSettled: () => void
}

function gridItemElements(gridElement: HTMLElement, itemClassName: string): HTMLElement[] {
  return Array.from(gridElement.children).filter((element): element is HTMLElement => (
    element instanceof HTMLElement && element.classList.contains(itemClassName)
  ))
}

/** Reconciles Muuri's item list with the React-rendered children, in DOM order. */
function syncMuuriItems(grid: MuuriGrid, domItems: HTMLElement[], observer: ResizeObserver | null) {
  const domItemSet = new Set(domItems)
  const muuriItems = grid.getItems()
  const knownElements = new Set<HTMLElement>()
  const removedItems: MuuriItem[] = []
  for (const item of muuriItems) {
    const element = item.getElement()
    if (element && domItemSet.has(element)) {
      knownElements.add(element)
    } else {
      removedItems.push(item)
      if (element) observer?.unobserve(element)
    }
  }
  if (removedItems.length > 0) grid.remove(removedItems, { removeElements: false, layout: false })

  const addedElements = domItems.filter(element => !knownElements.has(element))
  if (addedElements.length > 0) {
    grid.add(addedElements, { layout: false })
    for (const element of addedElements) observer?.observe(element)
  }

  const orderedItems = domItems
    .map(element => grid.getItem(element))
    .filter((item): item is MuuriItem => Boolean(item))
  if (orderedItems.length === grid.getItems().length) grid.sort(orderedItems, { layout: false })
}

/**
 * Masonry layout + drag-to-reorder backed by Muuri (loaded lazily).
 * Relayout happens only when the item set/order or grid metrics change, or an item resizes —
 * not on every data refresh.
 */
export function useMuuriLayout({
  gridRef,
  scrollRef,
  metrics,
  dragEnabled,
  itemClassName,
  itemClasses,
  layoutKey,
  onDragStart,
  onDragEnd,
  onDragSettled,
}: MuuriLayoutOptions) {
  const gridInstanceRef = useRef<MuuriGrid | null>(null)
  const resizeObserverRef = useRef<ResizeObserver | null>(null)
  const metricsRef = useRef(metrics)
  const isDraggingRef = useRef(false)
  const suppressClickRef = useRef(false)
  const callbacksRef = useRef({ onDragStart, onDragEnd, onDragSettled })
  const [isReady, setIsReady] = useState(false)
  const hasMetrics = metrics !== null

  useLayoutEffect(() => {
    metricsRef.current = metrics
    callbacksRef.current = { onDragStart, onDragEnd, onDragSettled }
  })

  useEffect(() => {
    const gridElement = gridRef.current
    if (!gridElement || !hasMetrics) return

    let disposed = false
    let layoutFrame = 0
    let settleFrame = 0
    let suppressTimer = 0
    let cleanup: (() => void) | null = null

    import('muuri').then(({ default: Muuri }) => {
      if (disposed) return

      const grid = new Muuri(gridElement, {
        items: gridItemElements(gridElement, itemClassName),
        layout: (_grid, id, items, _width, _height, callback) => {
          const current = metricsRef.current
          if (!current) return
          const layout = buildMasonryLayoutSlots({
            heights: items.map(item => item.getHeight()),
            cols: current.cols,
            itemWidth: current.itemWidth,
            gap: GRID_GAP,
          })
          callback({ id, items, slots: layout.slots, styles: { height: `${layout.height}px` } })
        },
        // Width changes arrive through the metrics → layout effect; no second window listener.
        layoutOnResize: false,
        layoutDuration: 180,
        layoutEasing: 'ease',
        dragEnabled,
        dragContainer: gridElement,
        dragStartPredicate: (item, event) => {
          const element = item.getElement()
          if (!element || element.dataset.staticItem === 'true' || element.dataset.dragDisabled === 'true') return false
          return Muuri.ItemDrag.defaultStartPredicate(item, event, { distance: 6 })
        },
        dragSort: true,
        dragSortHeuristics: { sortInterval: 60, minDragDistance: 8, minBounceBackAngle: 1 },
        dragSortPredicate: { threshold: 65, action: 'swap', migrateAction: 'swap' },
        dragRelease: { duration: 180, easing: 'ease', useDragContainer: true },
        dragAutoScroll: {
          targets: () => (scrollRef.current ? [scrollRef.current] : []),
        },
        itemClass: itemClassName,
        itemDraggingClass: itemClasses.dragging,
        itemReleasingClass: itemClasses.releasing,
        itemHiddenClass: itemClasses.hidden,
        itemPositioningClass: itemClasses.positioning,
      })

      const scheduleLayout = () => {
        if (layoutFrame || isDraggingRef.current) return
        layoutFrame = window.requestAnimationFrame(() => {
          layoutFrame = 0
          if (!isDraggingRef.current) grid.refreshItems().layout()
        })
      }

      const resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(scheduleLayout)
      resizeObserverRef.current = resizeObserver
      for (const item of grid.getItems()) {
        const element = item.getElement()
        if (element) resizeObserver?.observe(element)
      }

      const handleDragStart = () => {
        isDraggingRef.current = true
        suppressClickRef.current = true
        window.clearTimeout(suppressTimer)
        callbacksRef.current.onDragStart()
      }

      const handleDragReleaseEnd = () => {
        const orderedIds = grid.getItems()
          .map(item => item.getElement()?.dataset.noteId)
          .filter((id): id is string => Boolean(id))
        callbacksRef.current.onDragEnd(orderedIds)
        window.cancelAnimationFrame(settleFrame)
        settleFrame = window.requestAnimationFrame(() => {
          settleFrame = 0
          isDraggingRef.current = false
          callbacksRef.current.onDragSettled()
          grid.refreshItems().layout()
          suppressTimer = window.setTimeout(() => {
            suppressClickRef.current = false
          }, DRAG_CLICK_SUPPRESSION_MS)
        })
      }

      grid.on('dragStart', handleDragStart)
      grid.on('dragReleaseEnd', handleDragReleaseEnd)
      gridInstanceRef.current = grid
      grid.refreshItems(undefined, true).layout(true)
      flushSync(() => setIsReady(true))

      cleanup = () => {
        grid.off('dragStart', handleDragStart)
        grid.off('dragReleaseEnd', handleDragReleaseEnd)
        resizeObserver?.disconnect()
        if (resizeObserverRef.current === resizeObserver) resizeObserverRef.current = null
        grid.destroy(false)
        if (gridInstanceRef.current === grid) gridInstanceRef.current = null
      }
    }).catch(error => {
      console.error('Failed to load the masonry grid', error)
    })

    return () => {
      disposed = true
      window.cancelAnimationFrame(layoutFrame)
      window.cancelAnimationFrame(settleFrame)
      window.clearTimeout(suppressTimer)
      isDraggingRef.current = false
      suppressClickRef.current = false
      cleanup?.()
    }
    // Item classes are static CSS-module names; the grid is rebuilt only when drag mode flips.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasMetrics, dragEnabled])

  useLayoutEffect(() => {
    const grid = gridInstanceRef.current
    const gridElement = gridRef.current
    if (!grid || !gridElement || !metrics || isDraggingRef.current) return
    syncMuuriItems(grid, gridItemElements(gridElement, itemClassName), resizeObserverRef.current)
    grid.refreshItems(undefined, true).layout()
  }, [layoutKey, metrics, isReady, gridRef, itemClassName])

  const handleClickCapture = useCallback((event: MouseEvent<HTMLDivElement>) => {
    if (!suppressClickRef.current) return
    event.preventDefault()
    event.stopPropagation()
  }, [])

  return { isReady, handleClickCapture }
}
