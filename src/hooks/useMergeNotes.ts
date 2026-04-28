import { useMutation, useQueryClient } from '@tanstack/react-query'
import { mergeNotes } from '../api/notes'
import type { Note } from '../types'

export function useMergeNotes() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ sourceSlug, targetSlug, title }: { sourceSlug: string; targetSlug: string; title?: string }) =>
      mergeNotes(sourceSlug, targetSlug, title),
    onSuccess: (mergedNote: Note, { sourceSlug }) => {
      // Immediately write the merged result into the cache
      queryClient.setQueriesData<Note[]>({ queryKey: ['notes'] }, old =>
        Array.isArray(old)
          ? old
              .filter(n => n.slug !== sourceSlug)
              .map(n => n.slug === mergedNote.slug ? mergedNote : n)
          : old,
      )
      queryClient.invalidateQueries({ queryKey: ['notes'] })
    },
  })
}
