import { apiFetch } from '../lib/apiClient.ts'

const blobUrlCache = new Map<string, string>()

export function cachedAuthenticatedBlobUrl(src: string): string | null {
  return blobUrlCache.get(src) ?? null
}

export async function authenticatedBlobUrl(src: string): Promise<string> {
  if (src.startsWith('blob:') || src.startsWith('data:')) return src

  const cached = blobUrlCache.get(src)
  if (cached) return cached

  const res = await apiFetch(src)
  if (!res.ok) throw new Error(`Failed to fetch protected asset: ${res.status}`)

  const blob = await res.blob()
  const objectUrl = URL.createObjectURL(blob)
  blobUrlCache.set(src, objectUrl)
  return objectUrl
}

export async function openAuthenticatedAsset(src: string): Promise<string> {
  const popup = typeof window !== 'undefined' ? window.open('', '_blank') : null
  if (popup) popup.opener = null

  try {
    const objectUrl = await authenticatedBlobUrl(src)
    if (popup) {
      popup.location.href = objectUrl
    } else if (typeof window !== 'undefined') {
      window.open(objectUrl, '_blank', 'noopener,noreferrer')
    }
    return objectUrl
  } catch (error) {
    popup?.close()
    throw error
  }
}
