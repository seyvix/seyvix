import { useLayoutEffect, useState } from 'react'

export function useLocalStorage<T>(key: string, initialValue: T) {
  const [value, setValue] = useState<T>(initialValue)

  useLayoutEffect(() => {
    try {
      if (typeof window === 'undefined') return
      const item = localStorage.getItem(key)
      if (item !== null) setValue(JSON.parse(item) as T)
    } catch {
      // ignore unavailable storage
    }
  }, [initialValue, key])

  const set = (newValue: T) => {
    setValue(newValue)
    try {
      localStorage.setItem(key, JSON.stringify(newValue))
    } catch {
      // ignore write errors (private mode, quota)
    }
  }

  return [value, set] as const
}
