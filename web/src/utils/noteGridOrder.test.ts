import test from 'node:test'
import assert from 'node:assert/strict'

import { buildMasonryLayoutSlots, calculateMasonryGridMetrics, orderNotesByIds, toReorderPayload } from './noteGridOrder.ts'

const notes = [
  { id: 'note-1', slug: 'first' },
  { id: 'note-2', slug: 'second' },
  { id: 'note-3', slug: 'third' },
]

test('orderNotesByIds follows visual note ids without mutating the input', () => {
  const moved = orderNotesByIds(notes, ['note-3', 'note-1', 'note-2'])

  assert.deepEqual(moved.map(note => note.slug), ['third', 'first', 'second'])
  assert.deepEqual(notes.map(note => note.slug), ['first', 'second', 'third'])
})

test('orderNotesByIds appends missing notes and ignores unknown visual ids', () => {
  const moved = orderNotesByIds(notes, ['note-3', 'unknown'])

  assert.deepEqual(moved.map(note => note.slug), ['third', 'first', 'second'])
})

test('toReorderPayload stores sparse custom positions by slug', () => {
  assert.deepEqual(toReorderPayload(notes), [
    { slug: 'first', position: 10 },
    { slug: 'second', position: 20 },
    { slug: 'third', position: 30 },
  ])
})

test('calculateMasonryGridMetrics keeps multiple columns when space allows', () => {
  assert.deepEqual(calculateMasonryGridMetrics(1600, 5), {
    cols: 5,
    itemWidth: 307,
    contentWidth: 1567,
  })
})

test('calculateMasonryGridMetrics grows cards when fewer columns are selected', () => {
  assert.deepEqual(calculateMasonryGridMetrics(1600, 2), {
    cols: 2,
    itemWidth: 780,
    contentWidth: 1568,
  })
})

test('calculateMasonryGridMetrics honors dense column selections when cards remain readable', () => {
  assert.deepEqual(calculateMasonryGridMetrics(1600, 7), {
    cols: 7,
    itemWidth: 217,
    contentWidth: 1567,
  })
})

test('calculateMasonryGridMetrics uses a single comfortable column on phones', () => {
  assert.deepEqual(calculateMasonryGridMetrics(390, 5), {
    cols: 1,
    itemWidth: 366,
    contentWidth: 366,
  })
})

test('buildMasonryLayoutSlots places every next card into the shortest column', () => {
  const layout = buildMasonryLayoutSlots({
    heights: [180, 420, 120, 240],
    cols: 2,
    itemWidth: 300,
    gap: 8,
  })

  assert.deepEqual(layout.slots, [
    0, 0,
    308, 0,
    0, 188,
    0, 316,
  ])
  assert.equal(layout.height, 556)
})
