import { useQuery } from '@tanstack/react-query'
import { fetchNote } from '../api/notes'

export function useNote(noteId: string) {
  return useQuery({
    queryKey: ['note', noteId],
    queryFn: () => fetchNote(noteId),
    enabled: !!noteId,
  })
}
