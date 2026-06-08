import { createContext, useContext, useLayoutEffect, useState } from 'react'

interface SettingsContextValue {
  cols: number
  setCols: (n: number) => void
}

const SettingsContext = createContext<SettingsContextValue | null>(null)

const KEY = 'seyvix:masonry-cols'
export function SettingsProvider({ children }: { children: React.ReactNode }) {
  const [cols, setCols] = useState<number>(5)

  useLayoutEffect(() => {
    try {
      const stored = localStorage.getItem(KEY)
      const n = stored ? Number(stored) : 5
      if (n >= 1 && n <= 7) setCols(n)
    } catch {
      // ignore unavailable storage
    }
  }, [])

  function handleSetCols(n: number) {
    setCols(n)
    try { localStorage.setItem(KEY, String(n)) } catch { /* ignore */ }
  }

  return (
    <SettingsContext.Provider value={{ cols, setCols: handleSetCols }}>
      {children}
    </SettingsContext.Provider>
  )
}

export function useSettings() {
  const ctx = useContext(SettingsContext)
  if (!ctx) throw new Error('useSettings must be used within SettingsProvider')
  return ctx
}
