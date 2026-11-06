import { apiFetch } from '../lib/apiClient.ts'
import { readJson } from '../lib/apiError.ts'
import type { SearchMode } from '../components/SearchBar/SearchBar'

export interface SearchCapabilities {
  noteCount: number
  threshold: number
  unlockedModes: SearchMode[]
  defaultMode: SearchMode
  /** False when the server runs without an AI provider (FTS-only search, no auto-enrichment). */
  aiEnabled?: boolean
}

export async function apiSearchCapabilities(): Promise<SearchCapabilities> {
  return readJson(await apiFetch('/api/v1/search/capabilities'), 'Failed to fetch search capabilities')
}
