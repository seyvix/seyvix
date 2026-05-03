import { useEffect, useRef, useState } from 'react'
import { apiFetch } from '../../lib/apiClient'
import { LoaderSpinner } from '../LoaderSpinner'
import styles from './HtmlSnapshotViewer.module.css'

interface Props {
  src: string
  className?: string
}

export default function HtmlSnapshotViewer({ src, className }: Props) {
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const [primeDone, setPrimeDone] = useState(false)
  const [docReady, setDocReady] = useState(false)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    setPrimeDone(false)
    setDocReady(false)
    setError(false)

    console.debug('[HtmlSnapshotViewer] priming snapshot cookie', { src })
    apiFetch(src)
      .then(r => {
        if (!r.ok) throw new Error('fetch failed')
        console.debug('[HtmlSnapshotViewer] cookie prime response', {
          src,
          status: r.status,
        })
        if (!cancelled) setPrimeDone(true)
      })
      .catch(err => {
        console.debug('[HtmlSnapshotViewer] cookie prime failed', { src, err })
        if (!cancelled) setError(true)
      })

    return () => {
      cancelled = true
    }
  }, [src])

  useEffect(() => {
    if (!primeDone || error) return
    const iframe = iframeRef.current
    if (!iframe) return

    let cancelled = false

    const finish = () => {
      if (cancelled) return
      setDocReady(true)
    }

    const onInnerDomReady = () => {
      try {
        const doc = iframe.contentDocument ?? iframe.contentWindow?.document
        if (doc && doc.readyState === 'loading') {
          doc.addEventListener('DOMContentLoaded', finish, { once: true })
          return
        }
        if (doc) {
          finish()
          return
        }
      } catch {
        /* cross-origin or blocked */
      }
      finish()
    }

    iframe.addEventListener('load', onInnerDomReady, { once: true })

    return () => {
      cancelled = true
      iframe.removeEventListener('load', onInnerDomReady)
      try {
        const doc = iframe.contentDocument ?? iframe.contentWindow?.document
        doc?.removeEventListener('DOMContentLoaded', finish)
      } catch {
        /* ignore */
      }
    }
  }, [primeDone, error, src])

  function handleFrameError() {
    console.debug('[HtmlSnapshotViewer] iframe load error', { src })
    setError(true)
  }

  if (error) {
    return (
      <div className={styles.errorRoot}>
        Не удалось загрузить снимок страницы
      </div>
    )
  }

  const showOverlay = !primeDone || !docReady

  return (
    <div className={styles.viewRoot}>
      {primeDone && (
        <iframe
          ref={iframeRef}
          src={src}
          className={`${styles.frame} ${className ?? ''}`}
          title="Archived page snapshot"
          sandbox="allow-same-origin"
          onError={handleFrameError}
        />
      )}
      {showOverlay && (
        <div className={styles.loadingOverlay} aria-busy="true">
          <LoaderSpinner />
        </div>
      )}
    </div>
  )
}
