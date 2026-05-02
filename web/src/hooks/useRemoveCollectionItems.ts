import { useMutation, useQueryClient } from '@tanstack/react-query'
import { removeCollectionItems } from '../api/notes'

export function useRemoveCollectionItems() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ collectionSlug, itemSlugs }: { collectionSlug: string; itemSlugs: string[] }) =>
      removeCollectionItems(collectionSlug, itemSlugs),

    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notes'] })
    },
  })
}
