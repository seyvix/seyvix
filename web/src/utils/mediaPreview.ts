import type { NoteObject } from '../types'

export interface VideoPreviewState {
  object: NoteObject
  isHovered: boolean
  isInViewport: boolean
  autoplayInViewport: boolean
  reducedMotion: boolean
}

export function canPreviewVideoCard(object: NoteObject): boolean {
  return object.type === 'video' && Boolean(object.content)
}

export function shouldActivateVideoPreview({
  object,
  isHovered,
  isInViewport,
  autoplayInViewport,
  reducedMotion,
}: VideoPreviewState): boolean {
  if (reducedMotion || !canPreviewVideoCard(object)) return false
  return autoplayInViewport ? isInViewport : isHovered
}

export function videoPreviewWindow(durationSeconds: number | null | undefined) {
  const duration = Number.isFinite(durationSeconds) && durationSeconds ? durationSeconds : 8
  return {
    start: 0,
    duration: Math.min(8, Math.max(1, Math.floor(duration))),
  }
}
