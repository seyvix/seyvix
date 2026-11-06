import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'

export interface UploadNotice {
  id: string
  message: string
}

const NOTICE_AUTO_DISMISS_MS = 7000

interface UploadContextValue {
  notices: UploadNotice[]
  pushNotice: (message: string) => void
  dismissNotice: (id: string) => void
}

const UploadContext = createContext<UploadContextValue | null>(null)

export function UploadProvider({ children }: { children: React.ReactNode }) {
  const [notices, setNotices] = useState<UploadNotice[]>([])
  const timersRef = useRef(new Map<string, number>())

  useEffect(() => {
    const timers = timersRef.current
    return () => {
      for (const timer of timers.values()) window.clearTimeout(timer)
      timers.clear()
    }
  }, [])

  const dismissNotice = useCallback((id: string) => {
    const timer = timersRef.current.get(id)
    if (timer !== undefined) window.clearTimeout(timer)
    timersRef.current.delete(id)
    setNotices(prev => prev.filter(n => n.id !== id))
  }, [])

  const pushNotice = useCallback((message: string) => {
    setNotices((prev) => {
      if (prev.some(n => n.message === message)) return prev
      const id = `notice-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
      timersRef.current.set(id, window.setTimeout(() => dismissNotice(id), NOTICE_AUTO_DISMISS_MS))
      return [...prev, { id, message }]
    })
  }, [dismissNotice])

  const value = useMemo(() => ({ notices, pushNotice, dismissNotice }), [notices, pushNotice, dismissNotice])

  return <UploadContext.Provider value={value}>{children}</UploadContext.Provider>
}

export function useUploadContext() {
  const ctx = useContext(UploadContext)
  if (!ctx) throw new Error('useUploadContext must be used within UploadProvider')
  return ctx
}
