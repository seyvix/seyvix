import { useEffect, useState } from 'react'
import { authenticatedBlobUrl, cachedAuthenticatedBlobUrl } from '../../utils/authenticatedBlobUrl'
import { LoaderSpinner } from '../LoaderSpinner'
import styles from './AuthImage.module.css'

interface AuthImageProps extends React.ImgHTMLAttributes<HTMLImageElement> {
  src: string
}

export default function AuthImage({ src, className, style, ...rest }: AuthImageProps) {
  const [blobUrl, setBlobUrl] = useState<string | null>(() => cachedAuthenticatedBlobUrl(src))
  const [imgReady, setImgReady] = useState(false)

  useEffect(() => {
    if (!src) return
    const cached = cachedAuthenticatedBlobUrl(src)
    if (cached) {
      setBlobUrl(cached)
      setImgReady(false)
      return
    }

    let cancelled = false
    setImgReady(false)
    authenticatedBlobUrl(src)
      .then(url => {
        if (cancelled) return
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
