import { createContext, useContext, useState, useCallback } from 'react'

export interface UploadJobEntry {
  jobId: string
  noteId: string
}

interface UploadContextValue {
  jobs: UploadJobEntry[]
  addJob: (entry: UploadJobEntry) => void
  removeJob: (jobId: string) => void
  hasActiveJobs: boolean
}

const UploadContext = createContext<UploadContextValue | null>(null)

export function UploadProvider({ children }: { children: React.ReactNode }) {
  const [jobs, setJobs] = useState<UploadJobEntry[]>([])

  const addJob = useCallback((entry: UploadJobEntry) => {
    setJobs(prev => prev.some(j => j.jobId === entry.jobId) ? prev : [...prev, entry])
  }, [])

  const removeJob = useCallback((jobId: string) => {
    setJobs(prev => prev.filter(j => j.jobId !== jobId))
  }, [])

  return (
    <UploadContext.Provider value={{ jobs, addJob, removeJob, hasActiveJobs: jobs.length > 0 }}>
      {children}
    </UploadContext.Provider>
  )
}

export function useUploadContext() {
  const ctx = useContext(UploadContext)
  if (!ctx) throw new Error('useUploadContext must be used within UploadProvider')
  return ctx
}
