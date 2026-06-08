import type { QueryClient } from '@tanstack/react-query'
import type { SearchCapabilities } from '../api/search.ts'
import type { Note, NotesParams } from '../types/index.ts'
import { normalizeSearchMode } from '../utils/searchMode.ts'

const SEARCH_CAPABILITIES_QUERY_KEY = ['search-capabilities'] as const

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
  const tags = paramList(url.searchParams, 'tags')
  const folders = paramList(url.searchParams, 'folders')
  const contentTypes = paramList(url.searchParams, 'types')
  const sources = paramList(url.searchParams, 'sources')
  const favorite = parseBool(url.searchParams.get('favorite'))
  const createdAfter = optionalParam(url.searchParams.get('created_after'))
  const createdBefore = optionalParam(url.searchParams.get('created_before'))

  return {
    search: search || undefined,
    searchMode,
    tags: tags.length ? tags : undefined,
    folders: folders.length ? folders : undefined,
    contentTypes: contentTypes.length ? contentTypes : undefined,
    sources: sources.length ? sources : undefined,
    favorite,
    createdAfter,
    createdBefore,
    sort: 'custom',
  }
}

function paramList(params: URLSearchParams, key: string): string[] {
  return Array.from(new Set(
    params
      .getAll(key)
      .flatMap(value => value.split(','))
      .map(value => value.trim())
      .filter(Boolean),
  ))
}

function optionalParam(value: string | null): string | null {
  const trimmed = value?.trim()
  return trimmed || null
}

function parseBool(value: string | null): boolean | null {
  if (value === 'true') return true
  if (value === 'false') return false
  return null
}

function notesQueryKey(params: NotesParams) {
  return ['notes', {
    search: params.search ?? null,
    searchMode: params.searchMode ?? null,
    sort: params.sort ?? null,
    tags: params.tags ?? [],
    folders: params.folders ?? [],
    contentTypes: params.contentTypes ?? [],
    sources: params.sources ?? [],
    favorite: params.favorite ?? null,
    createdAfter: params.createdAfter ?? null,
    createdBefore: params.createdBefore ?? null,
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
  url.searchParams.set('view', 'card')
  if (params.search) url.searchParams.set('search', params.search)
  if (params.search && params.searchMode) url.searchParams.set('search_mode', params.searchMode)
  if (params.sort) url.searchParams.set('sort', params.sort)
  params.tags?.forEach(tag => url.searchParams.append('tags', tag))
  params.folders?.forEach(folder => url.searchParams.append('folders', folder))
  params.contentTypes?.forEach(type => url.searchParams.append('types', type))
  params.sources?.forEach(source => url.searchParams.append('sources', source))
  if (params.favorite !== undefined && params.favorite !== null) {
    url.searchParams.set('favorite', String(params.favorite))
  }
  if (params.createdAfter) url.searchParams.set('created_after', params.createdAfter)
  if (params.createdBefore) url.searchParams.set('created_before', params.createdBefore)

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
