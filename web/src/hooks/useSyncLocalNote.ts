import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createNote, uploadNoteFiles } from '../api/notes'
import { useLocalNotes } from '../contexts/LocalNotesContext'
import { requestChangeFeedSync } from './useNotesChangeFeed'
import { type NotesQueryData, upsertNoteInNotesQueryData } from './useNotes'
import { revokeLocalPreviewUrls } from './useUploadFiles'
import type { Note } from '../types'

/** Retries creating a note that previously failed to reach the server. */
export function useSyncLocalNote() {
  const queryClient = useQueryClient()
  const { getPayload, updateLocalNote } = useLocalNotes()

  return useMutation({
    mutationFn: async (note: Note) => {
      const key = note.stableKey ?? note.id
      const payload = getPayload(key)
      if (!payload) throw new Error('No payload for local note')

      updateLocalNote(key, { isLoading: true })
      if (payload.files?.length) return uploadNoteFiles(payload.files, payload.fileText)
      if (payload.createData) return createNote(payload.createData)
      throw new Error('Unknown payload type')
    },

    onSuccess: (serverNote, localNote) => {
      const stableKey = localNote.stableKey ?? localNote.id
      updateLocalNote(stableKey, { ...serverNote, stableKey, isLoading: false, isLocal: false })
      queryClient.setQueriesData<NotesQueryData>({ queryKey: ['notes'] }, old =>
        upsertNoteInNotesQueryData(old, { ...serverNote, stableKey }),
      )
      revokeLocalPreviewUrls(localNote.objects)
      requestChangeFeedSync()
    },

    onError: (_err, note) => {
      updateLocalNote(note.stableKey ?? note.id, { isLoading: false })
    },
  })
}
