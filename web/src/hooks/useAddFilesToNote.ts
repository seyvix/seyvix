import { useMutation, useQueryClient } from '@tanstack/react-query'
import { addFilesToNote } from '../api/notes'
import { SEARCH_CAPABILITIES_QUERY_KEY } from './useSearchCapabilities'

export function useAddFilesToNote() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ noteId, files }: { noteId: string; files: File[] }) =>
      addFilesToNote(noteId, files),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notes'] })
      queryClient.invalidateQueries({ queryKey: SEARCH_CAPABILITIES_QUERY_KEY })
    },
  })
}
