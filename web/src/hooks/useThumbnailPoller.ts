import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { Note } from '../types'

const THUMBNAIL_POLL_INTERVAL_MS = 10_000

export function shouldPollThumbnails(notes: Note[], enabled = true): boolean {
  if (!enabled) return false
  return notes.some(n =>
    !n.isLocal &&
    !n.isLoading &&
    n.objects.some(o => {
      if (o.type === 'document') return o.thumbnailUrl === null
      return false
    })
  )
}

/**
 * Polls GET /notes while generated note previews are still pending.
 */
export function useThumbnailPoller(notes: Note[], options: { enabled?: boolean } = {}) {
  const queryClient = useQueryClient()
  const hasPending = shouldPollThumbnails(notes, options.enabled ?? true)

  useEffect(() => {
    if (!hasPending) return
    const id = setInterval(() => {
      queryClient.invalidateQueries({ queryKey: ['notes'] })
    }, THUMBNAIL_POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [hasPending, queryClient])
}
