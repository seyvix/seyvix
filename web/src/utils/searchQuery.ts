export type SearchModeValue = 'full_text' | 'semantic' | 'hybrid'

export interface SearchFilterState {
  text: string
  tags: string[]
  folders: string[]
  contentTypes: string[]
  sources: string[]
  favorite: boolean | null
  createdAfter: string | null
  createdBefore: string | null
  searchMode: SearchModeValue | null
}

export interface SearchFilterToken {
  key: string
  canonicalKey: SearchFilterKey
  value: string
  raw: string
}

export interface ParsedSearchInput extends SearchFilterState {
  filters: SearchFilterState
  activeToken: SearchFilterToken | null
}

export type SearchFilterKey =
  | 'tag'
  | 'category'
  | 'type'
  | 'source'
  | 'pinned'
  | 'after'
  | 'before'
  | 'mode'

interface Token {
  raw: string
  value: string
}

const FILTER_ALIASES: Record<string, SearchFilterKey> = {
  tag: 'tag',
  tags: 'tag',
  category: 'category',
  cat: 'category',
  folder: 'category',
  folders: 'category',
  type: 'type',
  kind: 'type',
  source: 'source',
  provider: 'source',
  pinned: 'pinned',
  pin: 'pinned',
  favorite: 'pinned',
  favourite: 'pinned',
  fav: 'pinned',
  after: 'after',
  from: 'after',
  before: 'before',
  until: 'before',
  mode: 'mode',
  searchmode: 'mode',
}

const VALID_SEARCH_MODES = new Set<SearchModeValue>(['full_text', 'semantic', 'hybrid'])

const EMPTY_FILTERS: SearchFilterState = {
  text: '',
  tags: [],
  folders: [],
  contentTypes: [],
  sources: [],
  favorite: null,
  createdAfter: null,
  createdBefore: null,
  searchMode: null,
}

export function parseSearchInput(
  input: string,
  options: { commitTrailingFilter?: boolean } = {},
): ParsedSearchInput {
  const tokens = tokenize(input)
  const filters: SearchFilterState = { ...EMPTY_FILTERS }
  const state: ParsedSearchInput = { ...filters, filters, activeToken: null }
  const freeText: string[] = []
  const hasTrailingWhitespace = /\s$/.test(input)

  tokens.forEach((token, index) => {
    const filter = parseFilterToken(token)
    if (filter === null) {
      freeText.push(token.value)
      return
    }

    const isTrailing = index === tokens.length - 1 && !hasTrailingWhitespace
    if (isTrailing && !options.commitTrailingFilter) {
      state.activeToken = filter
      return
    }
    applyFilterToken(filters, filter)
  })

  filters.text = freeText.join(' ').trim()
  return { ...filters, filters, activeToken: state.activeToken }
}

export function searchFiltersFromParams(params: URLSearchParams): SearchFilterState {
  const rawMode = params.get('searchMode')
  return {
    text: params.get('search') ?? '',
    tags: paramList(params, 'tags'),
    folders: paramList(params, 'folders'),
    contentTypes: paramList(params, 'types'),
    sources: paramList(params, 'sources'),
    favorite: parseBool(params.get('favorite')),
    createdAfter: optionalParam(params.get('created_after')),
    createdBefore: optionalParam(params.get('created_before')),
    searchMode: isSearchMode(rawMode) ? rawMode : null,
  }
}

export function searchFiltersToParams(
  params: URLSearchParams,
  filters: SearchFilterState,
  options: { defaultMode: SearchModeValue },
): URLSearchParams {
  for (const key of [
    'search',
    'tags',
    'folders',
    'types',
    'sources',
    'favorite',
    'created_after',
    'created_before',
    'searchMode',
  ]) {
    params.delete(key)
  }

  if (filters.text.trim()) params.set('search', filters.text.trim())
  for (const tag of uniqueNonEmpty(filters.tags)) params.append('tags', tag)
  for (const folder of uniqueNonEmpty(filters.folders)) params.append('folders', folder)
  for (const type of uniqueNonEmpty(filters.contentTypes)) params.append('types', type)
  for (const source of uniqueNonEmpty(filters.sources)) params.append('sources', source)
  if (filters.favorite !== null) params.set('favorite', String(filters.favorite))
  if (filters.createdAfter) params.set('created_after', filters.createdAfter)
  if (filters.createdBefore) params.set('created_before', filters.createdBefore)
  if (filters.searchMode && filters.searchMode !== options.defaultMode) {
    params.set('searchMode', filters.searchMode)
  }
  return params
}

export function buildSearchInput(
  filters: SearchFilterState,
  options: { defaultMode: SearchModeValue },
): string {
  const parts = []
  if (filters.text.trim()) parts.push(filters.text.trim())
  parts.push(...uniqueNonEmpty(filters.tags).map(value => `tag:${quoteFilterValue(value)}`))
  parts.push(...uniqueNonEmpty(filters.folders).map(value => `category:${quoteFilterValue(value)}`))
  parts.push(...uniqueNonEmpty(filters.contentTypes).map(value => `type:${quoteFilterValue(value)}`))
  parts.push(...uniqueNonEmpty(filters.sources).map(value => `source:${quoteFilterValue(value)}`))
  if (filters.favorite !== null) parts.push(`pinned:${filters.favorite}`)
  if (filters.createdAfter) parts.push(`after:${quoteFilterValue(filters.createdAfter)}`)
  if (filters.createdBefore) parts.push(`before:${quoteFilterValue(filters.createdBefore)}`)
  if (filters.searchMode && filters.searchMode !== options.defaultMode) {
    parts.push(`mode:${filters.searchMode}`)
  }
  return parts.join(' ')
}

export function emptySearchFilters(defaultMode: SearchModeValue): SearchFilterState {
  return { ...EMPTY_FILTERS, searchMode: defaultMode }
}

export function mergeSearchFilters(
  base: SearchFilterState,
  patch: Partial<SearchFilterState>,
): SearchFilterState {
  return {
    text: patch.text ?? base.text,
    tags: patch.tags ?? base.tags,
    folders: patch.folders ?? base.folders,
    contentTypes: patch.contentTypes ?? base.contentTypes,
    sources: patch.sources ?? base.sources,
    favorite: patch.favorite === undefined ? base.favorite : patch.favorite,
    createdAfter: patch.createdAfter === undefined ? base.createdAfter : patch.createdAfter,
    createdBefore: patch.createdBefore === undefined ? base.createdBefore : patch.createdBefore,
    searchMode: patch.searchMode === undefined ? base.searchMode : patch.searchMode,
  }
}

function tokenize(input: string): Token[] {
  const tokens: Token[] = []
  let raw = ''
  let value = ''
  let quote: '"' | "'" | null = null
  let escaping = false

  function flush() {
    if (!raw) return
    tokens.push({ raw, value })
    raw = ''
    value = ''
  }

  for (const char of input) {
    if (escaping) {
      raw += char
      value += char
      escaping = false
      continue
    }
    if (char === '\\' && quote !== null) {
      raw += char
      escaping = true
      continue
    }
    if (quote !== null) {
      raw += char
      if (char === quote) {
        quote = null
      } else {
        value += char
      }
      continue
    }
    if (char === '"' || char === "'") {
      raw += char
      quote = char
      continue
    }
    if (/\s/.test(char)) {
      flush()
      continue
    }
    raw += char
    value += char
  }
  flush()
  return tokens
}

function parseFilterToken(token: Token): SearchFilterToken | null {
  const index = token.value.indexOf(':')
  if (index <= 0) return null
  const key = token.value.slice(0, index).toLocaleLowerCase()
  const canonicalKey = FILTER_ALIASES[key]
  if (!canonicalKey) return null
  return {
    key,
    canonicalKey,
    value: token.value.slice(index + 1),
    raw: token.raw,
  }
}

function applyFilterToken(state: SearchFilterState, token: SearchFilterToken) {
  const value = token.value.trim()
  if (!value) return
  if (token.canonicalKey === 'tag') {
    state.tags = appendUnique(state.tags, value)
  } else if (token.canonicalKey === 'category') {
    state.folders = appendUnique(state.folders, value)
  } else if (token.canonicalKey === 'type') {
    state.contentTypes = appendUnique(state.contentTypes, normalizeTokenValue(value))
  } else if (token.canonicalKey === 'source') {
    state.sources = appendUnique(state.sources, normalizeTokenValue(value))
  } else if (token.canonicalKey === 'pinned') {
    const parsed = parseBool(value)
    if (parsed !== null) state.favorite = parsed
  } else if (token.canonicalKey === 'after') {
    state.createdAfter = value
  } else if (token.canonicalKey === 'before') {
    state.createdBefore = value
  } else if (token.canonicalKey === 'mode') {
    const normalized = normalizeTokenValue(value)
    if (isSearchMode(normalized)) state.searchMode = normalized
  }
}

function paramList(params: URLSearchParams, key: string): string[] {
  return uniqueNonEmpty(
    params
      .getAll(key)
      .flatMap(value => value.split(','))
      .map(value => value.trim()),
  )
}

function optionalParam(value: string | null): string | null {
  const trimmed = value?.trim()
  return trimmed || null
}

function parseBool(value: string | null): boolean | null {
  const normalized = value?.trim().toLocaleLowerCase()
  if (!normalized) return null
  if (['true', '1', 'yes', 'y', 'on', 'да'].includes(normalized)) return true
  if (['false', '0', 'no', 'n', 'off', 'нет'].includes(normalized)) return false
  return null
}

function normalizeTokenValue(value: string): string {
  return value.trim().toLocaleLowerCase()
}

function isSearchMode(value: string | null): value is SearchModeValue {
  return value !== null && VALID_SEARCH_MODES.has(value as SearchModeValue)
}

function appendUnique(values: string[], value: string): string[] {
  return uniqueNonEmpty([...values, value])
}

function uniqueNonEmpty(values: string[]): string[] {
  const seen = new Set<string>()
  const result: string[] = []
  for (const raw of values) {
    const value = raw.trim()
    if (!value) continue
    const key = value.toLocaleLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    result.push(value)
  }
  return result
}

function quoteFilterValue(value: string): string {
  if (!/[/"'\s:]/.test(value)) return value
  return `"${value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`
}
