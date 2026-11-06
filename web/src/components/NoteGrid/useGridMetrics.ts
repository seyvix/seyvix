import { useLayoutEffect, useState, type RefObject } from 'react'
import { calculateMasonryGridMetrics, type MasonryGridMetrics } from '../../utils/noteGridOrder'

function sameMetrics(a: MasonryGridMetrics | null, b: MasonryGridMetrics): boolean {
  return a !== null && a.cols === b.cols && a.itemWidth === b.itemWidth && a.contentWidth === b.contentWidth
}

/** Column count / item width derived from the scroll container width; stable object while unchanged. */
export function useGridMetrics(containerRef: RefObject<HTMLElement | null>, cols: number): MasonryGridMetrics | null {
  const [metrics, setMetrics] = useState<MasonryGridMetrics | null>(null)

  useLayoutEffect(() => {
    const container = containerRef.current
    if (!container) return
    const update = (width: number) => {
      const next = calculateMasonryGridMetrics(width, cols)
      setMetrics(current => (sameMetrics(current, next) ? current : next))
    }
    update(container.clientWidth)

    if (typeof ResizeObserver === 'undefined') {
      const handleResize = () => update(container.clientWidth)
      window.addEventListener('resize', handleResize)
      return () => window.removeEventListener('resize', handleResize)
    }
    const observer = new ResizeObserver(entries => {
      const entry = entries[0]
      if (entry) update(entry.contentRect.width)
    })
    observer.observe(container)
    return () => observer.disconnect()
  }, [containerRef, cols])

  return metrics
}
