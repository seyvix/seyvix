import { useQuery } from '@tanstack/react-query'
import { fetchNotes } from '../api/notes'
import type { NotesParams } from '../types'

export function useNotes(params: NotesParams = {}) {
  return useQuery({
    queryKey: ['notes', params],
    queryFn: () => fetchNotes(params),
    refetchInterval: () => (
      typeof document !== 'undefined' && document.visibilityState === 'visible'
        ? 2000
        : false
    ),
    refetchOnWindowFocus: 'always',
  })
}
