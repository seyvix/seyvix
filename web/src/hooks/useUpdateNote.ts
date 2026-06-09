import { useMutation, useQueryClient } from '@tanstack/react-query'
import { updateNote } from '../api/notes'
import { SEARCH_CAPABILITIES_QUERY_KEY } from './useSearchCapabilities'
import { type NotesQueryData, replaceNoteInNotesQueryData } from './useNotes'
import type { Note } from '../types'

export function useUpdateNote() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ noteRef, data }: { noteRef: string; data: Parameters<typeof updateNote>[1] }) =>
      updateNote(noteRef, data),
    onSuccess: (updatedNote: Note) => {
      queryClient.invalidateQueries({ queryKey: ['note', updatedNote.id] })
      // Immediately apply the updated note into the cache
      queryClient.setQueriesData<NotesQueryData>({ queryKey: ['notes'] }, old =>
        replaceNoteInNotesQueryData(old, updatedNote),
      )
      queryClient.invalidateQueries({ queryKey: ['notes'] })
      queryClient.invalidateQueries({ queryKey: SEARCH_CAPABILITIES_QUERY_KEY })
    },
  })
}
