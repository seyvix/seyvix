import { useCallback, useState } from 'react'

function readValue<T>(key: string, fallback: T): T {
  try {
    const item = localStorage.getItem(key)
    return item === null ? fallback : JSON.parse(item) as T
  } catch {
    return fallback // unavailable storage or corrupt JSON
  }
}

/** State persisted to localStorage under `key` (the SPA renders client-side only). */
export function useLocalStorage<T>(key: string, initialValue: T) {
  const [value, setValue] = useState<T>(() => readValue(key, initialValue))

  const set = useCallback((newValue: T) => {
    setValue(newValue)
    try {
      localStorage.setItem(key, JSON.stringify(newValue))
    } catch {
      // quota/privacy mode: the value just won't persist
    }
  }, [key])

  return [value, set] as const
}
