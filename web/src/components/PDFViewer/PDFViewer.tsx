import { useState } from 'react'
import { useAuthenticatedObjectUrl } from '../../hooks/useAuthenticatedObjectUrl'
import { LoaderSpinner } from '../LoaderSpinner'
import styles from './PDFViewer.module.css'

interface PDFViewerProps {
  /** Authenticated API URL of the PDF; fetched with the bearer token and shown via a blob URL. */
  src: string
  className?: string
}

/** Browser-native PDF viewer for protected files (default export so it can be lazy-loaded). */
export default function PDFViewer({ src, className }: PDFViewerProps) {
  const { url, error, retry } = useAuthenticatedObjectUrl(src)
  const [loadedUrl, setLoadedUrl] = useState<string | null>(null)

  if (error) {
    return (
      <div className={styles.error}>
        <span>Не удалось загрузить PDF</span>
        <button type="button" onClick={retry}>Повторить</button>
      </div>
    )
  }

  return (
    <div className={className ? `${styles.root} ${className}` : styles.root}>
      {(!url || loadedUrl !== url) && (
        <div className="appLoaderOverlay" aria-hidden>
          <LoaderSpinner />
        </div>
      )}
      {url && <iframe src={url} className={styles.frame} title="PDF" onLoad={() => setLoadedUrl(url)} />}
    </div>
  )
}
