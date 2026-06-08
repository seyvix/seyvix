import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildSearchInput,
  parseSearchInput,
  searchFiltersFromParams,
  searchFiltersToParams,
} from './searchQuery.ts'

test('parseSearchInput extracts completed filters and keeps free text', () => {
  const parsed = parseSearchInput('new game tag:games category:"Games/Strategy" type:video source:telegram pinned:true after:2026-05-01 before:2026-06-01 mode:semantic ')

  assert.equal(parsed.text, 'new game')
  assert.deepEqual(parsed.filters.tags, ['games'])
  assert.deepEqual(parsed.filters.folders, ['Games/Strategy'])
  assert.deepEqual(parsed.filters.contentTypes, ['video'])
  assert.deepEqual(parsed.filters.sources, ['telegram'])
  assert.equal(parsed.filters.favorite, true)
  assert.equal(parsed.filters.createdAfter, '2026-05-01')
  assert.equal(parsed.filters.createdBefore, '2026-06-01')
  assert.equal(parsed.filters.searchMode, 'semantic')
  assert.equal(parsed.activeToken, null)
})

test('parseSearchInput exposes unfinished filter token without applying it', () => {
  const parsed = parseSearchInput('new game category:strat')

  assert.equal(parsed.text, 'new game')
  assert.deepEqual(parsed.filters.folders, [])
  assert.deepEqual(parsed.activeToken, {
    key: 'category',
    canonicalKey: 'category',
    value: 'strat',
    raw: 'category:strat',
  })
})

test('parseSearchInput can commit the trailing filter token', () => {
  const parsed = parseSearchInput('игра tag:rts', { commitTrailingFilter: true })

  assert.equal(parsed.text, 'игра')
  assert.deepEqual(parsed.filters.tags, ['rts'])
  assert.equal(parsed.activeToken, null)
})

test('searchFilters round-trip through URL params without dropping old filters', () => {
  const params = new URLSearchParams()
  params.set('search', 'new game')
  params.append('tags', 'games')
  params.append('folders', 'Games/Strategy')
  params.append('types', 'video')
  params.append('sources', 'telegram')
  params.set('favorite', 'true')
  params.set('created_after', '2026-05-01')
  params.set('created_before', '2026-06-01')
  params.set('searchMode', 'hybrid')

  const parsed = searchFiltersFromParams(params)
  assert.deepEqual(parsed, {
    text: 'new game',
    tags: ['games'],
    folders: ['Games/Strategy'],
    contentTypes: ['video'],
    sources: ['telegram'],
    favorite: true,
    createdAfter: '2026-05-01',
    createdBefore: '2026-06-01',
    searchMode: 'hybrid',
  })

  const next = new URLSearchParams()
  searchFiltersToParams(next, parsed, { defaultMode: 'hybrid' })

  assert.equal(next.get('search'), 'new game')
  assert.deepEqual(next.getAll('tags'), ['games'])
  assert.deepEqual(next.getAll('folders'), ['Games/Strategy'])
  assert.deepEqual(next.getAll('types'), ['video'])
  assert.deepEqual(next.getAll('sources'), ['telegram'])
  assert.equal(next.get('favorite'), 'true')
  assert.equal(next.get('created_after'), '2026-05-01')
  assert.equal(next.get('created_before'), '2026-06-01')
  assert.equal(next.get('searchMode'), null)
})

test('buildSearchInput renders active filters as editable tokens', () => {
  const input = buildSearchInput({
    text: 'new game',
    tags: ['games'],
    folders: ['Games/Strategy'],
    contentTypes: ['video'],
    sources: ['telegram'],
    favorite: true,
    createdAfter: '2026-05-01',
    createdBefore: null,
    searchMode: 'hybrid',
  }, { defaultMode: 'full_text' })

  assert.equal(input, 'new game tag:games category:"Games/Strategy" type:video source:telegram pinned:true after:2026-05-01 mode:hybrid')
})
