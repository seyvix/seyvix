import { createContext, useContext, useState, useCallback, type ReactNode } from 'react'

interface BulkSelectContextValue {
  isBulk: boolean
  selectedSlugs: Set<string>
  toggleBulk: () => void
  toggleSelect: (slug: string) => void
  clearSelection: () => void
}

const BulkSelectContext = createContext<BulkSelectContextValue | null>(null)

export function BulkSelectProvider({ children }: { children: ReactNode }) {
  const [isBulk, setIsBulk] = useState(false)
  const [selectedSlugs, setSelectedSlugs] = useState(new Set<string>())

  const toggleBulk = useCallback(() => {
    setIsBulk(v => {
      if (v) setSelectedSlugs(new Set())
      return !v
    })
  }, [])

  const toggleSelect = useCallback((slug: string) => {
    setSelectedSlugs(prev => {
      const next = new Set(prev)
      next.has(slug) ? next.delete(slug) : next.add(slug)
      return next
    })
  }, [])

  const clearSelection = useCallback(() => setSelectedSlugs(new Set()), [])

  return (
    <BulkSelectContext.Provider value={{ isBulk, selectedSlugs, toggleBulk, toggleSelect, clearSelection }}>
      {children}
    </BulkSelectContext.Provider>
  )
}

const NOOP = () => {}
const DEFAULT: BulkSelectContextValue = {
  isBulk: false,
  selectedSlugs: new Set(),
  toggleBulk: NOOP,
  toggleSelect: NOOP,
  clearSelection: NOOP,
}

export function useBulkSelect(): BulkSelectContextValue {
  return useContext(BulkSelectContext) ?? DEFAULT
}
