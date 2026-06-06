import { useMutation, useQueryClient } from '@tanstack/react-query'
import { deleteNotes } from '../api/notes'
import { useLocalNotes } from '../contexts/LocalNotesContext'
import { useBulkSelect } from '../contexts/BulkSelectContext'
import { SEARCH_CAPABILITIES_QUERY_KEY } from './useSearchCapabilities'
import type { Note } from '../types'

export function useBulkDeleteNotes() {
  const queryClient = useQueryClient()
  const { removeLocalNote } = useLocalNotes()
  const { toggleBulk, clearSelection } = useBulkSelect()

  return useMutation({
    mutationFn: (slugs: string[]) => deleteNotes(slugs),

    onMutate: async (slugs: string[]) => {
      const slugSet = new Set(slugs)

      // Optimistically remove from cache
      queryClient.setQueriesData<Note[]>({ queryKey: ['notes'] }, old =>
        Array.isArray(old) ? old.filter(n => !slugSet.has(n.slug)) : old,
      )

      // Remove local notes
      slugs.forEach(slug => removeLocalNote(slug))

      return { slugSet }
    },

    onSuccess: (_data, _vars, ctx) => {
      // Ensure server state is consistent
      queryClient.invalidateQueries({ queryKey: ['notes'] })
      queryClient.invalidateQueries({ queryKey: SEARCH_CAPABILITIES_QUERY_KEY })
      clearSelection()
      toggleBulk()
    },

    onError: (_err, _vars, _ctx) => {
      // Revert: re-fetch from server
      queryClient.invalidateQueries({ queryKey: ['notes'] })
      queryClient.invalidateQueries({ queryKey: SEARCH_CAPABILITIES_QUERY_KEY })
    },
  })
}
