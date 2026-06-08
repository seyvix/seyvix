import type { QueryClient } from '@tanstack/react-query'
import type { SearchCapabilities } from '../api/search'
import { SEARCH_CAPABILITIES_QUERY_KEY } from '../hooks/useSearchCapabilities'
import type { Note, NotesParams } from '../types'
import { normalizeSearchMode } from '../utils/searchMode'

const FALLBACK_CAPABILITIES: SearchCapabilities = {
  noteCount: 0,
  threshold: Number.POSITIVE_INFINITY,
  unlockedModes: ['full_text'],
  defaultMode: 'full_text',
}

export async function prefetchNotesRoute(
  queryClient: QueryClient,
  request: Request,
  accessToken: string | null,
): Promise<void> {
  if (!accessToken) return

  const requestUrl = new URL(request.url)
  if (requestUrl.pathname !== '/notes') return

  const apiBaseUrl = process.env.SSR_API_BASE_URL ?? process.env.VITE_API_PROXY_TARGET
  if (!apiBaseUrl) return

  try {
    const capabilities = await queryClient.fetchQuery({
      queryKey: SEARCH_CAPABILITIES_QUERY_KEY,
      queryFn: () => fetchSearchCapabilities(apiBaseUrl, accessToken),
      staleTime: 30_000,
    })
    const notesParams = buildNotesParams(requestUrl, capabilities)

    await queryClient.prefetchQuery({
      queryKey: notesQueryKey(notesParams),
      queryFn: () => fetchNotes(apiBaseUrl, accessToken, notesParams),
    })
  } catch (error) {
    console.warn('[framework-ssr] notes prefetch failed:', error)
  }
}

function buildNotesParams(url: URL, capabilities: SearchCapabilities): NotesParams {
  const search = url.searchParams.get('search') ?? ''
  const searchMode = normalizeSearchMode(url.searchParams.get('searchMode'), capabilities)
  const tags = url.searchParams.get('tags')?.split(',').filter(Boolean) ?? []
  const folders = url.searchParams.get('folders')?.split(',').filter(Boolean) ?? []

  return {
    search: search || undefined,
    searchMode,
    tags: tags.length ? tags : undefined,
    folders: folders.length ? folders : undefined,
    sort: 'custom',
  }
}

function notesQueryKey(params: NotesParams) {
  return ['notes', {
    search: params.search ?? null,
    searchMode: params.searchMode ?? null,
    sort: params.sort ?? null,
    tags: params.tags ?? [],
    folders: params.folders ?? [],
  }] as const
}

async function fetchSearchCapabilities(
  apiBaseUrl: string,
  accessToken: string,
): Promise<SearchCapabilities> {
  const response = await fetch(new URL('/api/v1/search/capabilities', apiBaseUrl), {
    headers: authenticatedHeaders(accessToken),
  })

  if (!response.ok) return FALLBACK_CAPABILITIES
  return await response.json() as SearchCapabilities
}

async function fetchNotes(
  apiBaseUrl: string,
  accessToken: string,
  params: NotesParams,
): Promise<Note[]> {
  const url = new URL('/api/v1/notes', apiBaseUrl)
  if (params.search) url.searchParams.set('search', params.search)
  if (params.search && params.searchMode) url.searchParams.set('search_mode', params.searchMode)
  if (params.sort) url.searchParams.set('sort', params.sort)
  params.tags?.forEach(tag => url.searchParams.append('tags', tag))
  params.folders?.forEach(folder => url.searchParams.append('folders', folder))

  const response = await fetch(url, {
    headers: authenticatedHeaders(accessToken),
  })

  if (!response.ok) throw new Error(`Failed to fetch notes for SSR: ${response.status}`)
  const data: unknown = await response.json()
  if (Array.isArray(data)) return data as Note[]
  return ((data as { items?: Note[] }).items ?? []) as Note[]
}

function authenticatedHeaders(accessToken: string): HeadersInit {
  return {
    Accept: 'application/json',
    Authorization: `Bearer ${accessToken}`,
  }
}
