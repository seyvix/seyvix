import { useEffect, useId, useRef, useState, type CSSProperties } from 'react'
import { Video } from 'lucide-react'
import AuthImage from '../AuthImage/AuthImage'
import type { NoteObject } from '../../types'
import { useSettings } from '../../contexts/SettingsContext'
import { useMediaQuery } from '../../hooks/useMediaQuery'
import { shouldActivateVideoPreview, videoPreviewWindow } from '../../utils/mediaPreview'
import styles from './NoteCard.module.css'

type VisibilityListener = (visible: boolean) => void

// One observer for every video card in the grid instead of one per card.
let sharedObserver: IntersectionObserver | null = null
const visibilityListeners = new Map<Element, VisibilityListener>()

function observeVisibility(element: Element, listener: VisibilityListener): () => void {
  if (typeof IntersectionObserver === 'undefined') return () => {}
  sharedObserver ??= new IntersectionObserver(
    entries => {
      for (const entry of entries) visibilityListeners.get(entry.target)?.(entry.isIntersecting)
    },
    { threshold: 0.55, rootMargin: '80px 0px' },
  )
  visibilityListeners.set(element, listener)
  sharedObserver.observe(element)
  return () => {
    visibilityListeners.delete(element)
    sharedObserver?.unobserve(element)
  }
}

// play() rejects with AbortError/NotAllowedError whenever the preview is interrupted (pointer left,
// card scrolled away, autoplay policy); the static thumbnail stays visible, so nothing to report.
function ignorePlaybackInterruption() {}

function VideoPreviewOverlay() {
  const gradientId = `video-preview-gradient-${useId().replace(/:/g, '')}`
  return (
    <span className={styles.videoPreviewOverlay} aria-hidden="true">
      <svg className={styles.videoPreviewGradientDefs} width="0" height="0" focusable="false">
        <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#5539e2" />
          <stop offset="54%" stopColor="#388ce3" />
          <stop offset="100%" stopColor="#18c2e5" />
        </linearGradient>
      </svg>
      <Video className={styles.videoPreviewIcon} size={34} stroke={`url(#${gradientId})`} strokeWidth={2.25} />
    </span>
  )
}

/** Video thumbnail that plays a short muted clip on hover / when visible (per user setting). */
export function VideoPreviewFrame({
  src,
  className,
  style,
  object,
}: {
  src: string
  className: string
  style?: CSSProperties
  object: NoteObject
}) {
  const frameRef = useRef<HTMLSpanElement>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const { videoPreviewAutoplay } = useSettings()
  const reducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)')
  const fineHover = useMediaQuery('(hover: hover) and (pointer: fine)')
  const [isHovered, setIsHovered] = useState(false)
  const [isInViewport, setIsInViewport] = useState(false)
  const active = shouldActivateVideoPreview({
    object,
    isHovered: fineHover && isHovered,
    isInViewport,
    autoplayInViewport: videoPreviewAutoplay,
    reducedMotion,
  })

  useEffect(() => {
    const element = frameRef.current
    if (!element || !videoPreviewAutoplay || reducedMotion) {
      setIsInViewport(false)
      return
    }
    return observeVisibility(element, setIsInViewport)
  }, [videoPreviewAutoplay, reducedMotion])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    if (!active) {
      if (video.hasAttribute('src')) {
        video.pause()
        video.removeAttribute('src')
        video.load()
      }
      return
    }
    video.src = object.content
    video.currentTime = 0
    video.play().catch(ignorePlaybackInterruption)
  }, [active, object.content])

  function handleTimeUpdate() {
    const video = videoRef.current
    if (!video) return
    const preview = videoPreviewWindow(video.duration)
    if (video.currentTime >= preview.start + preview.duration) {
      video.currentTime = preview.start
      video.play().catch(ignorePlaybackInterruption)
    }
  }

  return (
    <span
      ref={frameRef}
      className={[styles.videoPreviewFrame, active ? styles.videoPreviewFrameActive : '', className].filter(Boolean).join(' ')}
      style={style}
      onMouseEnter={fineHover ? () => setIsHovered(true) : undefined}
      onMouseLeave={fineHover ? () => setIsHovered(false) : undefined}
    >
      <AuthImage className={styles.videoPreviewImage} src={src} alt="" />
      <video
        ref={videoRef}
        className={styles.videoPreviewClip}
        muted
        playsInline
        preload="none"
        onLoadedMetadata={event => {
          event.currentTarget.currentTime = videoPreviewWindow(event.currentTarget.duration).start
        }}
        onTimeUpdate={handleTimeUpdate}
        onError={() => setIsHovered(false)}
        aria-hidden="true"
      />
      <VideoPreviewOverlay />
    </span>
  )
}
