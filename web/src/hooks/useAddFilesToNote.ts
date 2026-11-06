import { useMutation, useQueryClient } from '@tanstack/react-query'
import { addFilesToNote } from '../api/notes'
import { SEARCH_CAPABILITIES_QUERY_KEY } from './useSearchCapabilities'
import { requestChangeFeedSync } from './useNotesChangeFeed'
import { type NotesQueryData, replaceNoteInNotesQueryData } from './useNotes'

export function useAddFilesToNote() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ noteId, files }: { noteId: string; files: File[] }) => addFilesToNote(noteId, files),
    onSuccess: (updatedNote) => {
      queryClient.setQueriesData<NotesQueryData>({ queryKey: ['notes'] }, old =>
        replaceNoteInNotesQueryData(old, updatedNote) ?? old,
      )
      void queryClient.invalidateQueries({ queryKey: ['note', updatedNote.id] })
      void queryClient.invalidateQueries({ queryKey: ['note', updatedNote.slug] })
      void queryClient.invalidateQueries({ queryKey: SEARCH_CAPABILITIES_QUERY_KEY })
      requestChangeFeedSync()
    },
  })
}
