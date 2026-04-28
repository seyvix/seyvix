import { useMutation, useQueryClient } from '@tanstack/react-query'
import { mergeNotes } from '../api/notes'

export function useMergeNotes() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ sourceSlug, targetSlug, title }: { sourceSlug: string; targetSlug: string; title?: string }) =>
      mergeNotes(sourceSlug, targetSlug, title),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notes'] })
    },
  })
}
