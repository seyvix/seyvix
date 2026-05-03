import { useEffect, useState } from 'react'
import { LoaderSpinner } from '../LoaderSpinner'
import styles from './PDFViewer.module.css'

interface PDFViewerProps {
  src: string
}

export default function PDFViewer({ src }: PDFViewerProps) {
  const [frameReady, setFrameReady] = useState(false)

  useEffect(() => {
    setFrameReady(false)
  }, [src])

  return (
    <div className={styles.root}>
      {!frameReady && (
        <div className="appLoaderOverlay" aria-hidden>
          <LoaderSpinner />
        </div>
      )}
      <iframe
        src={src}
        className={styles.frame}
        title="PDF"
        onLoad={() => setFrameReady(true)}
      />
    </div>
  )
}
