import { useQuery } from '@tanstack/react-query'
import { apiSearchCapabilities, type SearchCapabilities } from '../api/search'

export const SEARCH_CAPABILITIES_QUERY_KEY = ['search-capabilities'] as const

const FALLBACK_CAPABILITIES: SearchCapabilities = {
  noteCount: 0,
  threshold: Number.POSITIVE_INFINITY,
  unlockedModes: ['full_text'],
  defaultMode: 'full_text',
}

export function useSearchCapabilities() {
  const query = useQuery({
    queryKey: SEARCH_CAPABILITIES_QUERY_KEY,
    queryFn: apiSearchCapabilities,
    staleTime: 30_000,
  })
  return {
    capabilities: query.data ?? FALLBACK_CAPABILITIES,
    isLoading: query.isLoading,
    isError: query.isError,
  }
}
