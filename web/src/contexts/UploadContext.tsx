import { createContext, useContext, useState, useCallback } from 'react'

export interface UploadJobEntry {
  jobId: string
  noteId: string
  label?: string
}

export interface UploadNotice {
  id: string
  message: string
}

const NOTICE_AUTO_DISMISS_MS = 7000

interface UploadContextValue {
  jobs: UploadJobEntry[]
  addJob: (entry: UploadJobEntry) => void
  removeJob: (jobId: string) => void
  hasActiveJobs: boolean
  notices: UploadNotice[]
  pushNotice: (message: string) => void
  dismissNotice: (id: string) => void
}

const UploadContext = createContext<UploadContextValue | null>(null)

export function UploadProvider({ children }: { children: React.ReactNode }) {
  const [jobs, setJobs] = useState<UploadJobEntry[]>([])
  const [notices, setNotices] = useState<UploadNotice[]>([])

  const addJob = useCallback((entry: UploadJobEntry) => {
    setJobs(prev => prev.some(j => j.jobId === entry.jobId) ? prev : [...prev, entry])
  }, [])

  const removeJob = useCallback((jobId: string) => {
    setJobs(prev => prev.filter(j => j.jobId !== jobId))
  }, [])

  const dismissNotice = useCallback((id: string) => {
    setNotices(prev => prev.filter(n => n.id !== id))
  }, [])

  const pushNotice = useCallback((message: string) => {
    const id = `notice-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
    setNotices(prev => {
      if (prev.some(n => n.message === message)) return prev
      return [...prev, { id, message }]
    })
    window.setTimeout(() => dismissNotice(id), NOTICE_AUTO_DISMISS_MS)
  }, [dismissNotice])

  return (
    <UploadContext.Provider value={{
      jobs, addJob, removeJob,
      hasActiveJobs: jobs.length > 0,
      notices, pushNotice, dismissNotice,
    }}>
      {children}
    </UploadContext.Provider>
  )
}

export function useUploadContext() {
  const ctx = useContext(UploadContext)
  if (!ctx) throw new Error('useUploadContext must be used within UploadProvider')
  return ctx
}
