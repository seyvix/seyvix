import { useState } from 'react'

export function useLocalStorage<T>(key: string, initialValue: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const item = localStorage.getItem(key)
      return item !== null ? (JSON.parse(item) as T) : initialValue
    } catch {
      return initialValue
    }
  })

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
