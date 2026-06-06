import type { SearchMode } from '../components/SearchBar/SearchBar'
import type { SearchCapabilities } from '../api/search'

const VALID: SearchMode[] = ['full_text', 'semantic', 'hybrid']

function isSearchMode(value: unknown): value is SearchMode {
  return typeof value === 'string' && (VALID as string[]).includes(value)
}

export function normalizeSearchMode(
  candidate: SearchMode | string | null | undefined,
  capabilities: SearchCapabilities,
): SearchMode {
  if (!isSearchMode(candidate)) return capabilities.defaultMode
  if (!capabilities.unlockedModes.includes(candidate)) return capabilities.defaultMode
  return candidate
}
