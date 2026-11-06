import { useCallback, useSyncExternalStore } from 'react'

const mediaQueryLists = new Map<string, MediaQueryList>()

function getMediaQueryList(query: string): MediaQueryList | null {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return null
  let media = mediaQueryLists.get(query)
  if (!media) {
    media = window.matchMedia(query)
    mediaQueryLists.set(query, media)
  }
  return media
}

/** Subscribes to a CSS media query; `false` during SSR / when matchMedia is unavailable. */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback((onChange: () => void) => {
    const media = getMediaQueryList(query)
    if (!media) return () => {}
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [query])

  return useSyncExternalStore(
    subscribe,
    () => getMediaQueryList(query)?.matches ?? false,
    () => false,
  )
}
