import { useMutation, useQueryClient } from '@tanstack/react-query'
import { addFilesToNote } from '../api/notes'

export function useAddFilesToNote() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ noteId, files }: { noteId: string; files: File[] }) =>
      addFilesToNote(noteId, files),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notes'] })
    },
  })
}
