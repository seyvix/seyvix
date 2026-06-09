import { useMutation, useQueryClient } from '@tanstack/react-query'
import { mergeNotes } from '../api/notes'
import { mergeNoteInNotesQueryData, type NotesQueryData } from './useNotes'
import type { Note } from '../types'

export function useMergeNotes() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ sourceSlug, targetSlug, title }: { sourceSlug: string; targetSlug: string; title?: string }) =>
      mergeNotes(sourceSlug, targetSlug, title),
    onSuccess: (mergedNote: Note, { sourceSlug }) => {
      // Immediately write the merged result into the cache
      queryClient.setQueriesData<NotesQueryData>({ queryKey: ['notes'] }, old =>
        mergeNoteInNotesQueryData(old, mergedNote, sourceSlug),
      )
      queryClient.invalidateQueries({ queryKey: ['notes'] })
    },
  })
}
