import { useEffect, useState } from 'react'
import {
  authenticatedBlobUrl,
  cachedAuthenticatedBlobUrl,
} from '../utils/authenticatedBlobUrl'

export function useAuthenticatedObjectUrl(src: string) {
  const [url, setUrl] = useState<string | null>(() => cachedAuthenticatedBlobUrl(src))
  const [loading, setLoading] = useState(() => !cachedAuthenticatedBlobUrl(src))
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    const cached = cachedAuthenticatedBlobUrl(src)
    if (cached) {
      setUrl(cached)
      setLoading(false)
      setError(false)
      return () => { cancelled = true }
    }

    setUrl(null)
    setLoading(true)
    setError(false)
    authenticatedBlobUrl(src)
      .then(objectUrl => {
        if (cancelled) return
        setUrl(objectUrl)
        setLoading(false)
      })
      .catch(() => {
        if (cancelled) return
        setError(true)
        setLoading(false)
      })

    return () => { cancelled = true }
  }, [src])

  return { url, loading, error }
}
