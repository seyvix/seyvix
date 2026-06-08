import { createContext, useContext, useLayoutEffect, useState } from 'react'

interface SettingsContextValue {
  cols: number
  setCols: (n: number) => void
  videoPreviewAutoplay: boolean
  setVideoPreviewAutoplay: (enabled: boolean) => void
}

const SettingsContext = createContext<SettingsContextValue | null>(null)

const KEY = 'seyvix:masonry-cols'
const VIDEO_PREVIEW_AUTOPLAY_KEY = 'seyvix:video-preview-autoplay'
export function SettingsProvider({ children }: { children: React.ReactNode }) {
  const [cols, setCols] = useState<number>(5)
  const [videoPreviewAutoplay, setVideoPreviewAutoplay] = useState(true)

  useLayoutEffect(() => {
    try {
      const stored = localStorage.getItem(KEY)
      const n = stored ? Number(stored) : 5
      if (n >= 1 && n <= 7) setCols(n)
      const storedVideoPreviewAutoplay = localStorage.getItem(VIDEO_PREVIEW_AUTOPLAY_KEY)
      setVideoPreviewAutoplay(
        storedVideoPreviewAutoplay === null ? true : storedVideoPreviewAutoplay === '1',
      )
    } catch {
      // ignore unavailable storage
    }
  }, [])

  function handleSetCols(n: number) {
    setCols(n)
    try { localStorage.setItem(KEY, String(n)) } catch { /* ignore */ }
  }

  function handleSetVideoPreviewAutoplay(enabled: boolean) {
    setVideoPreviewAutoplay(enabled)
    try {
      localStorage.setItem(VIDEO_PREVIEW_AUTOPLAY_KEY, enabled ? '1' : '0')
    } catch { /* ignore */ }
  }

  return (
    <SettingsContext.Provider
      value={{
        cols,
        setCols: handleSetCols,
        videoPreviewAutoplay,
        setVideoPreviewAutoplay: handleSetVideoPreviewAutoplay,
      }}
    >
      {children}
    </SettingsContext.Provider>
  )
}

export function useSettings() {
  const ctx = useContext(SettingsContext)
  if (!ctx) throw new Error('useSettings must be used within SettingsProvider')
  return ctx
}
