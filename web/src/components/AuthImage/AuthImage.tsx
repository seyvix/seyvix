import { useState } from 'react'
import { ImageOff } from 'lucide-react'
import { useAuthenticatedObjectUrl } from '../../hooks/useAuthenticatedObjectUrl'
import { cachedAuthenticatedBlobUrl } from '../../utils/authenticatedBlobUrl'
import { LoaderSpinner } from '../LoaderSpinner'
import styles from './AuthImage.module.css'

interface AuthImageProps extends React.ImgHTMLAttributes<HTMLImageElement> {
  src: string
}

export default function AuthImage({ src, className, style, alt = '', ...rest }: AuthImageProps) {
  const { url, error, retry } = useAuthenticatedObjectUrl(src)
  // Cached URLs were decoded before: skip the loader overlay for them (no flicker on scroll).
  const [decodedUrl, setDecodedUrl] = useState<string | null>(() => cachedAuthenticatedBlobUrl(src))
  const wrapperClassName = [styles.imageWrap, className].filter(Boolean).join(' ')
  const showLoader = !error && (!url || decodedUrl !== url)

  return (
    <span className={wrapperClassName} style={style}>
      {showLoader && (
        <span className={`${styles.imageLoader} appLoaderOverlay`} aria-hidden>
          <LoaderSpinner size="md" />
        </span>
      )}
      {error ? (
        <button
          type="button"
          className={styles.errorState}
          onClick={(event) => {
            event.preventDefault()
            event.stopPropagation()
            retry()
          }}
          title="Не удалось загрузить изображение. Нажми, чтобы повторить."
          aria-label="Повторить загрузку изображения"
        >
          <ImageOff size={20} strokeWidth={1.6} aria-hidden />
        </button>
      ) : url ? (
        <img
          {...rest}
          alt={alt}
          src={url}
          className={styles.imageImg}
          onLoad={() => setDecodedUrl(url)}
          onError={() => setDecodedUrl(url)}
        />
      ) : (
        <span className={styles.placeholder} />
      )}
    </span>
  )
}
