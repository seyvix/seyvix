import { apiFetch } from '../lib/apiClient'
import type { SearchMode } from '../components/SearchBar/SearchBar'

export interface SearchCapabilities {
  noteCount: number
  threshold: number
  unlockedModes: SearchMode[]
  defaultMode: SearchMode
}

const BASE = '/api/v1/search'

export async function apiSearchCapabilities(): Promise<SearchCapabilities> {
  const res = await apiFetch(`${BASE}/capabilities`)
  if (!res.ok) throw new Error('Failed to fetch search capabilities')
  const data = (await res.json()) as SearchCapabilities
  return data
}
