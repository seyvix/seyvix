import { useEffect, useState } from 'react'
import { apiFetch } from '../../lib/apiClient'
import { LoaderSpinner } from '../LoaderSpinner'
import styles from './HtmlSnapshotViewer.module.css'

interface Props {
  src: string
  className?: string
}

type PrimeState = 'priming' | 'ready' | 'error'

/**
 * Archived web page in a sandboxed iframe. The iframe cannot send the bearer token, so one
 * authenticated request first makes the API set a short-lived, artifact-scoped cookie that the
 * iframe (and the page's /resources/*) then use. Only the response headers are needed: the body
 * is cancelled instead of downloading the page twice.
 */
export default function HtmlSnapshotViewer({ src, className }: Props) {
  const [prime, setPrime] = useState<PrimeState>('priming')
  const [frameLoaded, setFrameLoaded] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    setPrime('priming')
    setFrameLoaded(false)
    apiFetch(src, { signal: controller.signal })
      .then(response => {
        if (!response.ok) throw new Error(`Snapshot request failed with ${response.status}`)
        void response.body?.cancel()
        setPrime('ready')
      })
      .catch(error => {
        if (controller.signal.aborted) return
        console.warn('Failed to open page snapshot', error)
        setPrime('error')
      })
    return () => controller.abort()
  }, [src])

  if (prime === 'error') {
    return <div className={styles.errorRoot}>Не удалось загрузить снимок страницы</div>
  }

  return (
    <div className={styles.viewRoot}>
      {prime === 'ready' && (
        <iframe
          src={src}
          className={className ? `${styles.frame} ${className}` : styles.frame}
          title="Снимок страницы"
          sandbox="allow-same-origin"
          onLoad={() => setFrameLoaded(true)}
          onError={() => setPrime('error')}
        />
      )}
      {!frameLoaded && (
        <div className={styles.loadingOverlay} aria-busy="true">
          <LoaderSpinner />
        </div>
      )}
    </div>
  )
}
