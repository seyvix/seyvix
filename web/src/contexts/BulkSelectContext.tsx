import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

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

  const value = useMemo(
    () => ({ isBulk, selectedSlugs, toggleBulk, toggleSelect, clearSelection }),
    [isBulk, selectedSlugs, toggleBulk, toggleSelect, clearSelection],
  )

  return <BulkSelectContext.Provider value={value}>{children}</BulkSelectContext.Provider>
}

export function useBulkSelect(): BulkSelectContextValue {
  const ctx = useContext(BulkSelectContext)
  if (!ctx) throw new Error('useBulkSelect must be used within BulkSelectProvider')
  return ctx
}
