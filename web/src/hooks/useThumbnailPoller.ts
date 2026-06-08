import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { Note } from '../types'

/**
 * Polls GET /notes every 3 seconds while generated note previews are still pending.
 */
export function useThumbnailPoller(notes: Note[]) {
  const queryClient = useQueryClient()

  const hasPending = notes.some(n =>
    !n.isLocal &&
    n.objects.some(o => {
      if (o.type === 'document') return o.thumbnailUrl === null
      return false
    })
  )

  useEffect(() => {
    if (!hasPending) return
    const id = setInterval(() => {
      queryClient.invalidateQueries({ queryKey: ['notes'] })
    }, 3000)
    return () => clearInterval(id)
  }, [hasPending, queryClient])
}
