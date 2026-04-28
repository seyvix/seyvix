import { createContext, useContext, useState, useCallback, useEffect } from 'react'
import type { Note } from '../types'

const STORAGE_KEY = 'seyvix_local_notes'

export interface LocalNotePayload {
  createData?: Partial<Note>
  files?: File[]
  fileText?: string
}

interface LocalNoteEntry {
  note: Note
  payload: LocalNotePayload
}

interface LocalNotesContextValue {
  localNotes: Note[]
  addLocalNote: (note: Note, payload: LocalNotePayload) => void
  updateLocalNote: (stableKey: string, updates: Partial<Note>) => void
  removeLocalNote: (stableKey: string) => void
  getPayload: (stableKey: string) => LocalNotePayload | undefined
}

const LocalNotesContext = createContext<LocalNotesContextValue | null>(null)

function readStorage(): LocalNoteEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

function writeStorage(entries: LocalNoteEntry[]) {
  const persistable = entries.filter(e => !e.payload.files && e.note.isLocal)
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(persistable)) } catch { /* quota */ }
}

function entryKey(e: LocalNoteEntry) {
  return e.note.stableKey ?? e.note.id
}

export function LocalNotesProvider({ children }: { children: React.ReactNode }) {
  const [entries, setEntries] = useState<LocalNoteEntry[]>([])

  useEffect(() => {
    const stored = readStorage()
    if (stored.length) setEntries(stored)
  }, [])

  const addLocalNote = useCallback((note: Note, payload: LocalNotePayload) => {
    setEntries(prev => {
      const key = note.stableKey ?? note.id
      const next = prev.some(e => entryKey(e) === key)
        ? prev.map(e => entryKey(e) === key ? { note, payload } : e)
        : [{ note, payload }, ...prev]
      writeStorage(next)
      return next
    })
  }, [])

  const updateLocalNote = useCallback((stableKey: string, updates: Partial<Note>) => {
    setEntries(prev => {
      const next = prev.map(e =>
        entryKey(e) === stableKey
          ? { ...e, note: { ...e.note, ...updates, stableKey: e.note.stableKey ?? e.note.id } }
          : e
      )
      writeStorage(next)
      return next
    })
  }, [])

  const removeLocalNote = useCallback((stableKey: string) => {
    setEntries(prev => {
      const next = prev.filter(e => entryKey(e) !== stableKey && e.note.slug !== stableKey)
      writeStorage(next)
      return next
    })
  }, [])

  const getPayload = useCallback((stableKey: string) => {
    return entries.find(e => entryKey(e) === stableKey)?.payload
  }, [entries])

  return (
    <LocalNotesContext.Provider value={{ localNotes: entries.map(e => e.note), addLocalNote, updateLocalNote, removeLocalNote, getPayload }}>
      {children}
    </LocalNotesContext.Provider>
  )
}

export function useLocalNotes() {
  const ctx = useContext(LocalNotesContext)
  if (!ctx) throw new Error('useLocalNotes must be used within LocalNotesProvider')
  return ctx
}
