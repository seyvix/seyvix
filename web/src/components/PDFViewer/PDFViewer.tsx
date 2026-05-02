import styles from './PDFViewer.module.css'

interface PDFViewerProps {
  src: string
}

export default function PDFViewer({ src }: PDFViewerProps) {
  return (
    <iframe
      src={src}
      className={styles.frame}
      title="PDF"
    />
  )
}
