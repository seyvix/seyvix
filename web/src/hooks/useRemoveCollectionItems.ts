import { useMutation, useQueryClient } from '@tanstack/react-query'
import { removeCollectionItems } from '../api/notes'
import { SEARCH_CAPABILITIES_QUERY_KEY } from './useSearchCapabilities'

export function useRemoveCollectionItems() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ collectionSlug, itemSlugs }: { collectionSlug: string; itemSlugs: string[] }) =>
      removeCollectionItems(collectionSlug, itemSlugs),

    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notes'] })
      // The collection's own detail cache ['note', collectionId] keeps the
      // removed items until invalidated; drop the prefix so the detail view
      // refetches when the user reopens it (and the dashboard preview, which
      // is derived from the same data, follows).
      queryClient.invalidateQueries({ queryKey: ['note'] })
      queryClient.invalidateQueries({ queryKey: SEARCH_CAPABILITIES_QUERY_KEY })
    },
  })
}
