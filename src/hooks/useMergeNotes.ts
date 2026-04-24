import { useMutation, useQueryClient } from '@tanstack/react-query'
import { mergeNotes } from '../api/notes'

export function useMergeNotes() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ sourceId, targetId }: { sourceId: string; targetId: string }) =>
      mergeNotes(sourceId, targetId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notes'] })
    },
  })
}
