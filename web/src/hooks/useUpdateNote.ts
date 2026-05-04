import { useMutation, useQueryClient } from '@tanstack/react-query'
import { updateNote } from '../api/notes'
import type { Note } from '../types'

export function useUpdateNote() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ noteRef, data }: { noteRef: string; data: Parameters<typeof updateNote>[1] }) =>
      updateNote(noteRef, data),
    onSuccess: (updatedNote: Note) => {
      queryClient.invalidateQueries({ queryKey: ['note', updatedNote.id] })
      // Immediately apply the updated note into the cache
      queryClient.setQueriesData<Note[]>({ queryKey: ['notes'] }, old =>
        Array.isArray(old)
          ? old.map(n => (n.id === updatedNote.id ? updatedNote : n))
          : old,
      )
      queryClient.invalidateQueries({ queryKey: ['notes'] })
    },
  })
}
