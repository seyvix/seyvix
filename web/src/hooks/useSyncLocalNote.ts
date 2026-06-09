import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createNote, startUploadJob } from '../api/notes'
import { useLocalNotes } from '../contexts/LocalNotesContext'
import { type NotesQueryData, upsertNoteInNotesQueryData } from './useNotes'
import type { Note } from '../types'

export function useSyncLocalNote() {
  const queryClient = useQueryClient()
  const { getPayload, updateLocalNote, removeLocalNote } = useLocalNotes()

  return useMutation({
    mutationFn: async (note: Note) => {
      const key = note.stableKey ?? note.id
      const payload = getPayload(key)
      if (!payload) throw new Error('No payload for local note')

      updateLocalNote(key, { isLoading: true })

      if (payload.files?.length) {
        const { noteId } = await startUploadJob(payload.files, payload.fileText)
        return { serverId: noteId, isUpload: true as const, stableKey: key }
      }
      if (payload.createData) {
        const serverNote = await createNote(payload.createData)
        return { serverNote, isUpload: false as const, stableKey: key }
      }
      throw new Error('Unknown payload type')
    },

    onSuccess: (result) => {
      if (result.isUpload) {
        updateLocalNote(result.stableKey, { id: result.serverId, slug: result.serverId, isLoading: false, isLocal: false })
        queryClient.invalidateQueries({ queryKey: ['notes'] })
      } else {
        updateLocalNote(result.stableKey, { ...result.serverNote, stableKey: result.stableKey, isLoading: false, isLocal: false })
        queryClient.setQueriesData<NotesQueryData>({ queryKey: ['notes'] }, old =>
          upsertNoteInNotesQueryData(old, result.serverNote),
        )
      }
    },

    onError: (_err, note) => {
      updateLocalNote(note.stableKey ?? note.id, { isLoading: false })
    },
  })
}
