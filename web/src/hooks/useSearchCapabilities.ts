import { useQuery } from '@tanstack/react-query'
import { apiSearchCapabilities, type SearchCapabilities } from '../api/search'

export const SEARCH_CAPABILITIES_QUERY_KEY = ['search-capabilities'] as const

const FALLBACK_CAPABILITIES: SearchCapabilities = {
  noteCount: 0,
  threshold: 0,
  unlockedModes: ['full_text'],
  defaultMode: 'full_text',
  aiEnabled: false,
}

function useCapabilitiesQuery() {
  return useQuery({
    queryKey: SEARCH_CAPABILITIES_QUERY_KEY,
    queryFn: apiSearchCapabilities,
    staleTime: 60_000,
  })
}

export function useSearchCapabilities() {
  const query = useCapabilitiesQuery()
  return {
    capabilities: query.data ?? FALLBACK_CAPABILITIES,
    isLoading: query.isLoading,
    isError: query.isError,
  }
}

/** Whether AI features (semantic search, auto tags/categories, OCR, profile suggestions) exist. */
export function useAiEnabled(): boolean {
  const { data } = useCapabilitiesQuery()
  // Unknown until loaded: hide AI-only UI rather than flash it. Older servers without the
  // field always had AI.
  return data ? data.aiEnabled !== false : false
}
