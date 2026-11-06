import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { Download, FastForward, Maximize2, Pause, Play, Rewind, Volume2, VolumeX } from 'lucide-react'
import { LoaderSpinner } from '../LoaderSpinner'
import type { NoteObject } from '../../types'
import { startDownload } from './download'
import { formatMediaTime } from './format'
import styles from './MediaPlayer.module.css'

const AUDIO_BAR_SCALES = Array.from({ length: 28 }, (_, index) => 0.28 + ((index * 7) % 13) / 16)

/** Custom audio/video player streaming the asset with range requests (preload=metadata). */
export function MediaPlayer({
  obj,
  title,
  sizeLabel,
  autoPlay = false,
  isFullscreen = false,
  onOpenFullscreen,
}: {
  obj: NoteObject
  title: string
  sizeLabel?: string
  autoPlay?: boolean
  isFullscreen?: boolean
  onOpenFullscreen?: () => void
}) {
  const mediaRef = useRef<HTMLMediaElement | null>(null)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState(false)
  const [playing, setPlaying] = useState(autoPlay)
  const [duration, setDuration] = useState(0)
  const [currentTime, setCurrentTime] = useState(0)
  const [bufferedEnd, setBufferedEnd] = useState(0)
  const [volume, setVolume] = useState(0.88)
  const [muted, setMuted] = useState(false)
  const isVideo = obj.type === 'video'

  useEffect(() => {
    const media = mediaRef.current
    if (!media) return
    media.volume = volume
    media.muted = muted
  }, [muted, volume])

  useEffect(() => {
    setReady(false)
    setError(false)
    setPlaying(autoPlay)
    setDuration(0)
    setCurrentTime(0)
    setBufferedEnd(0)
    if (autoPlay) mediaRef.current?.play().catch(() => setPlaying(false))
  }, [autoPlay, obj.content])

  function syncMediaState() {
    const media = mediaRef.current
    if (!media) return
    setCurrentTime(media.currentTime || 0)
    setDuration(Number.isFinite(media.duration) ? media.duration : 0)
    if (media.buffered.length > 0) setBufferedEnd(media.buffered.end(media.buffered.length - 1))
  }

  function togglePlay() {
    const media = mediaRef.current
    if (!media) return
    if (media.paused) {
      media.play().then(() => setPlaying(true)).catch(() => setPlaying(false))
    } else {
      media.pause()
      setPlaying(false)
    }
  }

  function seekTo(value: number) {
    const media = mediaRef.current
    if (!media) return
    media.currentTime = Math.max(0, Math.min(value, duration || value))
    syncMediaState()
  }

  const progress = duration > 0 ? Math.min(100, (currentTime / duration) * 100) : 0
  const buffer = duration > 0 ? Math.min(100, (bufferedEnd / duration) * 100) : 0
  const sliderStyle = {
    '--media-progress': `${progress}%`,
    '--media-buffer': `${Math.max(buffer, progress)}%`,
  } as CSSProperties

  const mediaEvents = {
    onLoadedMetadata: () => {
      setReady(true)
      syncMediaState()
    },
    onTimeUpdate: syncMediaState,
    onProgress: syncMediaState,
    onCanPlay: () => setReady(true),
    onPlay: () => setPlaying(true),
    onPause: () => setPlaying(false),
    onEnded: () => setPlaying(false),
    onError: () => {
      setReady(true)
      setError(true)
      setPlaying(false)
    },
  }

  return (
    <div className={[
      styles.streamingPlayer,
      isVideo ? styles.streamingVideoPlayer : styles.streamingAudioPlayer,
      isFullscreen ? styles.streamingPlayerFullscreen : '',
    ].filter(Boolean).join(' ')}>
      <div className={styles.streamingStage}>
        {!ready && !error && (
          <div className="appLoaderOverlay" aria-hidden>
            <LoaderSpinner />
          </div>
        )}
        {error && <div className={styles.mediaError}>Не удалось загрузить медиа</div>}
        {isVideo ? (
          <video
            ref={node => { mediaRef.current = node }}
            className={styles.streamingVideo}
            src={obj.content}
            poster={obj.thumbnailUrl ?? undefined}
            preload="metadata"
            playsInline
            {...mediaEvents}
          />
        ) : (
          <>
            <audio ref={node => { mediaRef.current = node }} src={obj.content} preload="metadata" {...mediaEvents} />
            <div className={styles.audioCanvas} aria-hidden>
              {AUDIO_BAR_SCALES.map((scale, index) => <span key={index} style={{ transform: `scaleY(${scale})` }} />)}
            </div>
          </>
        )}
      </div>

      <div className={styles.streamingControls}>
        <div className={styles.streamingPrimaryRow}>
          <button type="button" className={styles.mediaIconButton} onClick={() => seekTo((mediaRef.current?.currentTime ?? 0) - 10)} title="Назад на 10 секунд" aria-label="Назад на 10 секунд">
            <Rewind size={15} />
          </button>
          <button type="button" className={styles.mediaPlayButton} onClick={togglePlay} title={playing ? 'Пауза' : 'Воспроизвести'} aria-label={playing ? 'Пауза' : 'Воспроизвести'}>
            {playing ? <Pause size={18} /> : <Play size={18} />}
          </button>
          <button type="button" className={styles.mediaIconButton} onClick={() => seekTo((mediaRef.current?.currentTime ?? 0) + 15)} title="Вперёд на 15 секунд" aria-label="Вперёд на 15 секунд">
            <FastForward size={15} />
          </button>
          <div className={styles.mediaTitleBlock}>
            <span>{title}</span>
            <small>{sizeLabel ?? (isVideo ? 'Видео' : 'Аудио')}</small>
          </div>
          <button
            type="button"
            className={styles.mediaIconButton}
            onClick={() => setMuted(value => !value)}
            title={muted ? 'Включить звук' : 'Выключить звук'}
            aria-label={muted ? 'Включить звук' : 'Выключить звук'}
          >
            {muted || volume === 0 ? <VolumeX size={15} /> : <Volume2 size={15} />}
          </button>
          <input
            className={styles.volumeSlider}
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={muted ? 0 : volume}
            onChange={event => {
              const nextVolume = Number(event.target.value)
              setVolume(nextVolume)
              setMuted(nextVolume === 0)
            }}
            aria-label="Громкость"
          />
          <button
            type="button"
            className={styles.mediaIconButton}
            onClick={() => startDownload(obj.content, obj.filename ?? title)}
            title="Скачать файл"
            aria-label="Скачать файл"
          >
            <Download size={15} />
          </button>
          {onOpenFullscreen && (
            <button type="button" className={styles.mediaIconButton} onClick={onOpenFullscreen} title="На весь экран" aria-label="На весь экран">
              <Maximize2 size={15} />
            </button>
          )}
        </div>
        <div className={styles.mediaTimelineRow}>
          <span>{formatMediaTime(currentTime)}</span>
          <input
            className={styles.mediaTimeline}
            type="range"
            min={0}
            max={duration || 0}
            step={0.01}
            value={duration ? Math.min(currentTime, duration) : 0}
            style={sliderStyle}
            onChange={event => seekTo(Number(event.target.value))}
            disabled={!duration}
            aria-label="Позиция воспроизведения"
          />
          <span>{formatMediaTime(duration)}</span>
        </div>
      </div>
    </div>
  )
}
