import { createContext, useCallback, useContext, useMemo, useState } from 'react'

interface SettingsContextValue {
  cols: number
  setCols: (n: number) => void
  videoPreviewAutoplay: boolean
  setVideoPreviewAutoplay: (enabled: boolean) => void
}

const SettingsContext = createContext<SettingsContextValue | null>(null)

const COLS_KEY = 'seyvix:masonry-cols'
const VIDEO_PREVIEW_AUTOPLAY_KEY = 'seyvix:video-preview-autoplay'
const DEFAULT_COLS = 5

function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null // storage unavailable (privacy mode, sandboxed webview)
  }
}

function writeStored(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    // quota/privacy mode: the setting just won't persist
  }
}

function readCols(): number {
  const n = Number(readStored(COLS_KEY) ?? DEFAULT_COLS)
  return n >= 1 && n <= 7 ? n : DEFAULT_COLS
}

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  const [cols, setColsState] = useState(readCols)
  const [videoPreviewAutoplay, setAutoplayState] = useState(() => readStored(VIDEO_PREVIEW_AUTOPLAY_KEY) !== '0')

  const setCols = useCallback((n: number) => {
    setColsState(n)
    writeStored(COLS_KEY, String(n))
  }, [])

  const setVideoPreviewAutoplay = useCallback((enabled: boolean) => {
    setAutoplayState(enabled)
    writeStored(VIDEO_PREVIEW_AUTOPLAY_KEY, enabled ? '1' : '0')
  }, [])

  const value = useMemo(
    () => ({ cols, setCols, videoPreviewAutoplay, setVideoPreviewAutoplay }),
    [cols, setCols, videoPreviewAutoplay, setVideoPreviewAutoplay],
  )

  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>
}

export function useSettings() {
  const ctx = useContext(SettingsContext)
  if (!ctx) throw new Error('useSettings must be used within SettingsProvider')
  return ctx
}
