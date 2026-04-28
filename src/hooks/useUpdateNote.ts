import { useMutation, useQueryClient } from '@tanstack/react-query'
import { updateNote } from '../api/notes'
import type { Note } from '../types'

export function useUpdateNote() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ slug, data }: { slug: string; data: Parameters<typeof updateNote>[1] }) =>
      updateNote(slug, data),
    onSuccess: (updatedNote: Note) => {
      // Immediately apply the updated note into the cache
      queryClient.setQueriesData<Note[]>({ queryKey: ['notes'] }, old =>
        Array.isArray(old)
          ? old.map(n => n.slug === updatedNote.slug ? updatedNote : n)
          : old,
      )
      queryClient.invalidateQueries({ queryKey: ['notes'] })
    },
  })
}
