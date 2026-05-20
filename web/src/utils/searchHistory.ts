const MAX_SEARCH_HISTORY = 10

export const SEARCH_HISTORY_STORAGE_KEY = 'seyvix:search-history:v1'

export function nextSearchHistory(existing: string[], query: string): string[] {
  const normalized = query.trim()
  if (!normalized) return existing.slice(0, MAX_SEARCH_HISTORY)
  const seen = normalized.toLocaleLowerCase()
  return [
    normalized,
    ...existing.filter(item => item.trim().toLocaleLowerCase() !== seen),
  ].slice(0, MAX_SEARCH_HISTORY)
}

export function readSearchHistory(storage: Storage | undefined = globalThis.localStorage): string[] {
  try {
    const raw = storage?.getItem(SEARCH_HISTORY_STORAGE_KEY)
    const parsed: unknown = raw ? JSON.parse(raw) : []
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
      .slice(0, MAX_SEARCH_HISTORY)
  } catch {
    return []
  }
}

export function writeSearchHistory(history: string[], storage: Storage | undefined = globalThis.localStorage): void {
  try {
    storage?.setItem(SEARCH_HISTORY_STORAGE_KEY, JSON.stringify(history.slice(0, MAX_SEARCH_HISTORY)))
  } catch {
    // localStorage can be unavailable in private contexts.
  }
}
