import test from 'node:test'
import assert from 'node:assert/strict'

import { nextSearchHistory } from './searchHistory.ts'

test('nextSearchHistory stores latest unique non-empty searches', () => {
  const existing = Array.from({ length: 10 }, (_, index) => `query-${index + 1}`)

  const history = nextSearchHistory(existing, '  query-4  ')

  assert.deepEqual(history, [
    'query-4',
    'query-1',
    'query-2',
    'query-3',
    'query-5',
    'query-6',
    'query-7',
    'query-8',
    'query-9',
    'query-10',
  ])
})

test('nextSearchHistory caps history at ten items', () => {
  const existing = Array.from({ length: 10 }, (_, index) => `query-${index + 1}`)

  const history = nextSearchHistory(existing, 'new query')

  assert.equal(history.length, 10)
  assert.equal(history[0], 'new query')
  assert(!history.includes('query-10'))
})
