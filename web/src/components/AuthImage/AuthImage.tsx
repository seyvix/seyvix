import { useEffect, useState } from 'react'
import { apiFetch } from '../../lib/apiClient'
import styles from './AuthImage.module.css'

interface AuthImageProps extends React.ImgHTMLAttributes<HTMLImageElement> {
  src: string
}

const cache = new Map<string, string>()

export default function AuthImage({ src, className, style, ...rest }: AuthImageProps) {
  const [blobUrl, setBlobUrl] = useState<string | null>(() => cache.get(src) ?? null)

  useEffect(() => {
    if (!src) return
    if (cache.has(src)) {
      setBlobUrl(cache.get(src)!)
      return
    }

    let cancelled = false
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
    return <div className={`${styles.placeholder} ${className ?? ''}`} style={style} />
  }

  // eslint-disable-next-line jsx-a11y/alt-text
  return <img {...rest} src={blobUrl} className={className} style={style} />
}
