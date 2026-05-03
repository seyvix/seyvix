// Fetches favicons from Yandex favicon API.
// Returns a data URL (data:image/png;base64,...) or null on failure.

interface YandexFaviconSize {
  original_height: number
  original_width: number
  image: string
}

type YandexFaviconResponse = Array<Record<string, YandexFaviconSize>>

const cache = new Map<string, string | null>()
const inFlight = new Map<string, Promise<string | null>>()

export async function fetchFavicon(url: string): Promise<string | null> {
  if (cache.has(url)) return cache.get(url) ?? null

  const existing = inFlight.get(url)
  if (existing) return existing

  const promise = (async (): Promise<string | null> => {
    try {
      const apiUrl = `https://favicon.yandex.net/favicon/v2/${url}?json=1&allsizes=1`
      const res = await fetch(apiUrl, { signal: AbortSignal.timeout(6000) })
      if (!res.ok) return null

      const data: YandexFaviconResponse = await res.json()

      let bestSize = 0
      let bestImage = ''

      for (const item of data) {
        for (const [sizeStr, info] of Object.entries(item)) {
          const size = parseInt(sizeStr, 10)
          if (!isNaN(size) && size > bestSize && info?.image) {
            bestSize = size
            bestImage = info.image
          }
        }
      }

      return bestImage ? `data:image/png;base64,${bestImage}` : null
    } catch {
      return null
    }
  })().then(result => {
    cache.set(url, result)
    inFlight.delete(url)
    return result
  })

  inFlight.set(url, promise)
  return promise
}
