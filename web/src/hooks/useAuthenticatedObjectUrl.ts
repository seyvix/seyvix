import { useCallback, useEffect, useState } from 'react'
import {
  authenticatedBlobUrl,
  cachedAuthenticatedBlobUrl,
  retainAuthenticatedBlobUrl,
} from '../utils/authenticatedBlobUrl'

interface State {
  src: string | null
  url: string | null
  error: unknown
}

/**
 * Object URL for a protected asset, valid while the component is mounted (the URL is
 * reference-counted and never revoked while in use). `src = null` disables loading.
 */
export function useAuthenticatedObjectUrl(src: string | null) {
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<State>(() => ({
    src,
    url: src ? cachedAuthenticatedBlobUrl(src) : null,
    error: null,
  }))

  useEffect(() => {
    if (!src) {
      setState({ src, url: null, error: null })
      return
    }
    const release = retainAuthenticatedBlobUrl(src)
    let active = true
    const cached = cachedAuthenticatedBlobUrl(src)
    setState({ src, url: cached, error: null })
    if (!cached) {
      authenticatedBlobUrl(src).then(
        (url) => { if (active) setState({ src, url, error: null }) },
        (error: unknown) => { if (active) setState({ src, url: null, error }) },
      )
    }
    return () => {
      active = false
      release()
    }
  }, [src, attempt])

  const retry = useCallback(() => setAttempt(n => n + 1), [])
  // Ignore state left over from a previous `src` until the effect catches up.
  const current = state.src === src ? state : { url: null, error: null }

  return {
    url: current.url,
    loading: Boolean(src) && !current.url && !current.error,
    error: current.error,
    retry,
  }
}
