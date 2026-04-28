import { useEffect, useState } from 'react'
import { apiFetch } from '../../lib/apiClient'

interface AuthImageProps extends React.ImgHTMLAttributes<HTMLImageElement> {
  src: string
}

const cache = new Map<string, string>()

export default function AuthImage({ src, ...rest }: AuthImageProps) {
  const [blobUrl, setBlobUrl] = useState<string | null>(() => cache.get(src) ?? null)

  useEffect(() => {
    if (!src) return
    if (cache.has(src)) {
      setBlobUrl(cache.get(src)!)
      return
    }

    let revoked = false
    apiFetch(src)
      .then(res => {
        if (!res.ok) throw new Error('fetch failed')
        return res.blob()
      })
      .then(blob => {
        if (revoked) return
        const url = URL.createObjectURL(blob)
        cache.set(src, url)
        setBlobUrl(url)
      })
      .catch(() => {
        if (!revoked) setBlobUrl(src) // fallback: try without auth
      })

    return () => {
      revoked = true
    }
  }, [src])

  if (!blobUrl) return null
  // eslint-disable-next-line jsx-a11y/alt-text
  return <img {...rest} src={blobUrl} />
}
