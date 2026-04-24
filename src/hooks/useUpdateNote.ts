import { useMutation, useQueryClient } from '@tanstack/react-query'
import { updateNote } from '../api/notes'

export function useUpdateNote() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ slug, data }: { slug: string; data: Parameters<typeof updateNote>[1] }) =>
      updateNote(slug, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notes'] })
    },
  })
}
