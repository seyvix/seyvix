import { useEffect, useState } from 'react'
import { apiFetch } from '../../lib/apiClient'

interface AuthImageProps extends React.ImgHTMLAttributes<HTMLImageElement> {
  src: string
}

const cache = new Map<string, string>()

export default function AuthImage({ src, style, ...rest }: AuthImageProps) {
  const [blobUrl, setBlobUrl] = useState<string | null>(() => cache.get(src) ?? null)

  useEffect(() => {
    if (!src) return
    if (cache.has(src)) {
      setBlobUrl(cache.get(src)!)
      return
    }

    // Keep old blobUrl visible while loading the new src — avoids flicker on src change
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
        if (!cancelled) setBlobUrl(src) // fallback: try without auth
      })

    return () => {
      cancelled = true
    }
  }, [src])

  // Always render the element to avoid layout shifts; hide until ready
  // eslint-disable-next-line jsx-a11y/alt-text
  return (
    <img
      {...rest}
      src={blobUrl ?? ''}
      style={blobUrl ? style : { ...style, visibility: 'hidden' }}
    />
  )
}
