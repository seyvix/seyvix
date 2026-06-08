import { useEffect, useState } from 'react'
import { authenticatedBlobUrl, cachedAuthenticatedBlobUrl } from '../../utils/authenticatedBlobUrl'
import { LoaderSpinner } from '../LoaderSpinner'
import styles from './AuthImage.module.css'

interface AuthImageProps extends React.ImgHTMLAttributes<HTMLImageElement> {
  src: string
}

export default function AuthImage({ src, className, style, ...rest }: AuthImageProps) {
  const [blobUrl, setBlobUrl] = useState<string | null>(() => cachedAuthenticatedBlobUrl(src))
  const [imgReady, setImgReady] = useState(() => Boolean(cachedAuthenticatedBlobUrl(src)))
  const wrapperClassName = [styles.imageWrap, className].filter(Boolean).join(' ')

  useEffect(() => {
    if (!src) return
    const cached = cachedAuthenticatedBlobUrl(src)
    if (cached) {
      setBlobUrl(cached)
      setImgReady(true)
      return
    }

    let cancelled = false
    setBlobUrl(null)
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

  return (
    <span className={wrapperClassName} style={style}>
      {(!blobUrl || !imgReady) && (
        <span className={`${styles.imageLoader} appLoaderOverlay`} aria-hidden>
          <LoaderSpinner size="md" />
        </span>
      )}
      {blobUrl
        ? (
          // eslint-disable-next-line jsx-a11y/alt-text
          <img
            {...rest}
            src={blobUrl}
            className={styles.imageImg}
            onLoad={() => setImgReady(true)}
            onError={() => setImgReady(true)}
          />
        )
        : <span className={styles.placeholder} />}
    </span>
  )
}
