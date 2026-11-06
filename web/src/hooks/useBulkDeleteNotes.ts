import { useMutation, useQueryClient } from '@tanstack/react-query'
import { deleteNotes } from '../api/notes'
import { useLocalNotes } from '../contexts/LocalNotesContext'
import { useBulkSelect } from '../contexts/BulkSelectContext'
import { SEARCH_CAPABILITIES_QUERY_KEY } from './useSearchCapabilities'
import { type NotesQueryData, removeNotesFromNotesQueryData } from './useNotes'

export function useBulkDeleteNotes() {
  const queryClient = useQueryClient()
  const { removeLocalNote } = useLocalNotes()
  const { toggleBulk, clearSelection } = useBulkSelect()

  return useMutation({
    mutationFn: (slugs: string[]) => deleteNotes(slugs),

    onMutate: async (slugs: string[]) => {
      await queryClient.cancelQueries({ queryKey: ['notes'] })
      queryClient.setQueriesData<NotesQueryData>({ queryKey: ['notes'] }, old =>
        removeNotesFromNotesQueryData(old, slugs) ?? old,
      )
      slugs.forEach(slug => removeLocalNote(slug))
    },

    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['notes-trash'] })
      void queryClient.invalidateQueries({ queryKey: ['folders'] })
      void queryClient.invalidateQueries({ queryKey: SEARCH_CAPABILITIES_QUERY_KEY })
      clearSelection()
      toggleBulk()
    },

    onError: () => {
      // The optimistic removal may be wrong: reload the lists from the server.
      void queryClient.invalidateQueries({ queryKey: ['notes'] })
    },
  })
}
