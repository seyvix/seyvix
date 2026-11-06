import { useMutation, useQueryClient } from '@tanstack/react-query'
import { updateNote } from '../api/notes'
import { SEARCH_CAPABILITIES_QUERY_KEY } from './useSearchCapabilities'
import { requestChangeFeedSync } from './useNotesChangeFeed'
import { type NotesQueryData, replaceNoteInNotesQueryData } from './useNotes'
import type { Note } from '../types'

export function useUpdateNote() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ noteRef, data }: { noteRef: string; data: Parameters<typeof updateNote>[1] }) =>
      updateNote(noteRef, data),
    onSuccess: (updatedNote: Note) => {
      // The PATCH response is authoritative: patch lists in place instead of refetching them.
      queryClient.setQueriesData<NotesQueryData>({ queryKey: ['notes'] }, old =>
        replaceNoteInNotesQueryData(old, updatedNote) ?? old,
      )
      queryClient.setQueryData(['note', updatedNote.id], updatedNote)
      queryClient.setQueryData(['note', updatedNote.slug], updatedNote)
      void queryClient.invalidateQueries({ queryKey: SEARCH_CAPABILITIES_QUERY_KEY })
      // Text edits re-run enrichment server-side.
      requestChangeFeedSync()
    },
  })
}
