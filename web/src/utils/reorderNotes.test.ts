import test from 'node:test'
import assert from 'node:assert/strict'

import { moveSlug, orderBySlugs } from './reorderNotes.ts'

test('moveSlug inserts a slug before the target', () => {
  assert.deepEqual(
    moveSlug(['a', 'b', 'c', 'd'], 'd', 'b', 'before'),
    ['a', 'd', 'b', 'c'],
  )
})

test('moveSlug inserts a slug after the target', () => {
  assert.deepEqual(
    moveSlug(['a', 'b', 'c', 'd'], 'a', 'c', 'after'),
    ['b', 'c', 'a', 'd'],
  )
})

test('orderBySlugs keeps unknown items at the end', () => {
  const items = [{ slug: 'a' }, { slug: 'b' }, { slug: 'c' }]
  assert.deepEqual(orderBySlugs(items, ['c', 'a']), [{ slug: 'c' }, { slug: 'a' }, { slug: 'b' }])
})
