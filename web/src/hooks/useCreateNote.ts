import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createNote } from '../api/notes'
import { useLocalNotes } from '../contexts/LocalNotesContext'
import { SEARCH_CAPABILITIES_QUERY_KEY } from './useSearchCapabilities'
import type { Note } from '../types'

function makeTempId() {
  return `local-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

export function useCreateNote() {
  const queryClient = useQueryClient()
  const { addLocalNote, updateLocalNote } = useLocalNotes()

  return useMutation({
    mutationFn: createNote,

    onMutate: async (data: Partial<Note>) => {
      const stableKey = makeTempId()
      const optimistic: Note = {
        id: stableKey,
        slug: stableKey,
        stableKey,
        type: data.type ?? 'simple',
        title: data.title ?? '',
        cover: null,
        tags: data.tags ?? [],
        taxonomyCategory: data.taxonomyCategory ?? null,
        folderId: null,
        objects: data.objects ?? [],
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        isLocal: true,
        isLoading: true,
      }
      addLocalNote(optimistic, { createData: data })
      return { stableKey, createData: data, optimistic }
    },

    onSuccess: (serverNote, _vars, ctx) => {
      // Update fields in-place — card stays at same position
      updateLocalNote(ctx.stableKey, {
        ...serverNote,
        stableKey: ctx.stableKey, // preserve stable key
        isLoading: false,
        isLocal: false,
      })
      // Seed React Query cache so other queries see the new note
      queryClient.setQueriesData<Note[]>({ queryKey: ['notes'] }, old =>
        Array.isArray(old)
          ? [{ ...serverNote, stableKey: ctx.stableKey }, ...old.filter(n => n.id !== serverNote.id)]
          : [serverNote],
      )
      queryClient.invalidateQueries({ queryKey: SEARCH_CAPABILITIES_QUERY_KEY })
    },

    onError: (_err, _vars, ctx) => {
      if (!ctx) return
      updateLocalNote(ctx.stableKey, { isLoading: false, isLocal: true })
    },
  })
}
