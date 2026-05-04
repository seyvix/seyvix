import { useEffect, useState } from 'react'
import { apiFetch } from '../../lib/apiClient'
import { LoaderSpinner } from '../LoaderSpinner'
import styles from './AuthImage.module.css'

interface AuthImageProps extends React.ImgHTMLAttributes<HTMLImageElement> {
  src: string
}

const cache = new Map<string, string>()

export default function AuthImage({ src, className, style, ...rest }: AuthImageProps) {
  const [blobUrl, setBlobUrl] = useState<string | null>(() => cache.get(src) ?? null)
  const [imgReady, setImgReady] = useState(false)

  useEffect(() => {
    if (!src) return
    if (cache.has(src)) {
      setBlobUrl(cache.get(src)!)
      setImgReady(false)
      return
    }

    let cancelled = false
    setImgReady(false)
    apiFetch(src)
      .then(res => {
        if (!res.ok) throw new Error('fetch failed')
        return res.blob()
      })
      .then(blob => {
        if (cancelled) return
        const url = URL.createObjectURL(blob)
        cache.set(src, url)
        setBlobUrl(url)
      })
      .catch(() => {
        if (!cancelled) setBlobUrl(src)
      })

    return () => { cancelled = true }
  }, [src])

  if (!blobUrl) {
    return (
      <div className={`${styles.placeholder} appLoaderHost ${className ?? ''}`} style={style}>
        <LoaderSpinner size="md" />
      </div>
    )
  }

  // eslint-disable-next-line jsx-a11y/alt-text
  return (
    <span className={styles.imageWrap}>
      {!imgReady && (
        <span className={`${styles.imageLoader} appLoaderOverlay`} aria-hidden>
          <LoaderSpinner />
        </span>
      )}
      <img
        {...rest}
        src={blobUrl}
        className={`${styles.imageImg} ${className ?? ''}`}
        style={style}
        onLoad={() => setImgReady(true)}
        onError={() => setImgReady(true)}
      />
    </span>
  )
}
