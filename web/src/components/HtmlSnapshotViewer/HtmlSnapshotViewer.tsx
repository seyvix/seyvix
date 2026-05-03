import { useState, useEffect, useRef } from 'react'
import { apiFetch } from '../../lib/apiClient'
import styles from './HtmlSnapshotViewer.module.css'

interface Props {
  src: string
  className?: string
}

export default function HtmlSnapshotViewer({ src, className }: Props) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const urlRef = useRef<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(false)

    apiFetch(src)
      .then(r => {
        if (!r.ok) throw new Error('fetch failed')
        return r.blob()
      })
      .then(blob => {
        if (cancelled) return
        const url = URL.createObjectURL(blob)
        urlRef.current = url
        setBlobUrl(url)
        setLoading(false)
      })
      .catch(() => {
        if (!cancelled) {
          setError(true)
          setLoading(false)
        }
      })

    return () => {
      cancelled = true
      if (urlRef.current) {
        URL.revokeObjectURL(urlRef.current)
        urlRef.current = null
      }
    }
  }, [src])

  if (loading) {
    return (
      <div className={`${styles.state} ${className ?? ''}`}>
        <div className={styles.spinner} />
      </div>
    )
  }
  if (error) {
    return (
      <div className={`${styles.state} ${className ?? ''}`}>
        Не удалось загрузить снимок страницы
      </div>
    )
  }

  return (
    <iframe
      src={blobUrl!}
      className={`${styles.frame} ${className ?? ''}`}
      title="Archived page snapshot"
      sandbox=""
    />
  )
}
