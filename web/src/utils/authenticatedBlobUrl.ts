/**
 * Protected assets (thumbnails, media, documents) need the Bearer token, so they are fetched
 * with `apiFetch` and exposed to `<img>`/`<video>`/`<iframe>` as object URLs.
 *
 * Object URLs pin their Blob in memory until revoked, so this module owns their lifecycle:
 * - consumers `acquire` a URL and `release` it when unmounted (ref counting);
 * - a URL with live references is never revoked;
 * - unreferenced URLs stay cached (for instant re-display while scrolling/navigating) in LRU
 *   order and are revoked once the cache exceeds `MAX_IDLE_ENTRIES` or `MAX_IDLE_BYTES`.
 */

import { apiFetch } from '../lib/apiClient.ts'
import { ensureOk } from '../lib/apiError.ts'

const MAX_IDLE_ENTRIES = 200
const MAX_IDLE_BYTES = 64 * 1024 * 1024
/** A newly opened tab must finish loading the blob before its URL may be revoked. */
const OPENED_ASSET_HOLD_MS = 60_000

interface Entry {
  url: string
  size: number
}

// Map iteration order is insertion order: re-inserting on access gives LRU semantics.
const entries = new Map<string, Entry>()
const inFlight = new Map<string, Promise<string>>()
const refCounts = new Map<string, number>()

function isDirectUrl(src: string): boolean {
  return src.startsWith('blob:') || src.startsWith('data:')
}

function touch(src: string, entry: Entry): void {
  entries.delete(src)
  entries.set(src, entry)
}

function evictIdle(): void {
  let idleCount = 0
  let idleBytes = 0
  for (const [src, entry] of entries) {
    if (!refCounts.has(src)) {
      idleCount += 1
      idleBytes += entry.size
    }
  }
  for (const [src, entry] of entries) {
    if (idleCount <= MAX_IDLE_ENTRIES && idleBytes <= MAX_IDLE_BYTES) return
    if (refCounts.has(src)) continue
    entries.delete(src)
    URL.revokeObjectURL(entry.url)
    idleCount -= 1
    idleBytes -= entry.size
  }
}

/** Synchronous cache lookup (lets components render a cached asset without a loading flash). */
export function cachedAuthenticatedBlobUrl(src: string): string | null {
  if (isDirectUrl(src)) return src
  const entry = entries.get(src)
  if (!entry) return null
  touch(src, entry)
  return entry.url
}

/** Resolves an object URL for `src`, sharing concurrent fetches. Errors are `ApiError`s. */
export function authenticatedBlobUrl(src: string): Promise<string> {
  const cached = cachedAuthenticatedBlobUrl(src)
  if (cached) return Promise.resolve(cached)

  let pending = inFlight.get(src)
  if (!pending) {
    pending = (async () => {
      const res = await ensureOk(await apiFetch(src), 'Не удалось загрузить файл')
      const blob = await res.blob()
      const entry = { url: URL.createObjectURL(blob), size: blob.size }
      entries.set(src, entry)
      evictIdle()
      return entry.url
    })().finally(() => {
      inFlight.delete(src)
    })
    inFlight.set(src, pending)
  }
  return pending
}

/**
 * Marks `src` as in use until the returned `release` is called; its object URL will not be
 * revoked meanwhile. Call before (or together with) `authenticatedBlobUrl`.
 */
export function retainAuthenticatedBlobUrl(src: string): () => void {
  if (isDirectUrl(src)) return () => {}
  refCounts.set(src, (refCounts.get(src) ?? 0) + 1)
  let released = false
  return () => {
    if (released) return
    released = true
    const next = (refCounts.get(src) ?? 1) - 1
    if (next > 0) refCounts.set(src, next)
    else refCounts.delete(src)
    evictIdle()
  }
}

/** Warms the cache (e.g. on hover) without holding a reference. */
export function prefetchAuthenticatedBlobUrl(src: string): void {
  authenticatedBlobUrl(src).catch((error: unknown) => {
    console.warn('[assets] prefetch failed', src, error)
  })
}

/** Revokes everything (logout: the next user must not see the previous user's files). */
export function clearAuthenticatedBlobCache(): void {
  for (const entry of entries.values()) URL.revokeObjectURL(entry.url)
  entries.clear()
  refCounts.clear()
  inFlight.clear()
}

export async function openAuthenticatedAsset(src: string): Promise<string> {
  // Open synchronously (inside the click gesture) so popup blockers allow it.
  const popup = window.open('', '_blank')
  if (popup) popup.opener = null

  const release = retainAuthenticatedBlobUrl(src)
  try {
    const objectUrl = await authenticatedBlobUrl(src)
    if (popup) popup.location.href = objectUrl
    else window.open(objectUrl, '_blank', 'noopener,noreferrer')
    window.setTimeout(release, OPENED_ASSET_HOLD_MS)
    return objectUrl
  } catch (error) {
    release()
    popup?.close()
    throw error
  }
}
