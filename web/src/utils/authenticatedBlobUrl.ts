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
