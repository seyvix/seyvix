import { useState, useEffect } from 'react'
import { fetchFavicon } from '../utils/favicon'

export function useFavicon(url: string | null | undefined): string | null {
  const [src, setSrc] = useState<string | null>(null)

  useEffect(() => {
    if (!url) return
    let cancelled = false
    fetchFavicon(url).then(result => {
      if (!cancelled) setSrc(result)
    })
    return () => { cancelled = true }
  }, [url])

  return src
}
