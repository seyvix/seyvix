import test from 'node:test'
import assert from 'node:assert/strict'

import { dedupeNotes, notesQueryKey, notesRefetchInterval } from './useNotes.ts'
import type { Note } from '../types/index.ts'

test('notesQueryKey is derived from scalar search params', () => {
  assert.deepEqual(notesQueryKey({ search: 'Valheim', searchMode: 'hybrid', sort: 'custom' }), [
    'notes',
    {
      search: 'Valheim',
      searchMode: 'hybrid',
      sort: 'custom',
      tags: [],
      folders: [],
      contentTypes: [],
      sources: [],
      favorite: null,
      createdAfter: null,
      createdBefore: null,
    },
  ])
  assert.notDeepEqual(
    notesQueryKey({ search: 'Valheim', searchMode: 'hybrid' }),
    notesQueryKey({ search: 'Stronghold', searchMode: 'hybrid' }),
  )
  assert.notDeepEqual(
    notesQueryKey({ search: 'Valheim', contentTypes: ['video'] }),
    notesQueryKey({ search: 'Valheim', contentTypes: ['image'] }),
  )
})

test('notesRefetchInterval pauses active searches and polls compact idle notes frequently', () => {
  assert.equal(notesRefetchInterval({ search: 'Valheim' }, 'visible'), false)
  assert.equal(notesRefetchInterval({ tags: ['games'] }, 'visible'), false)
  assert.equal(notesRefetchInterval({}, 'hidden'), false)
  assert.equal(notesRefetchInterval({}, 'visible'), 2_000)
})

test('dedupeNotes keeps the first occurrence from refreshed pages', () => {
  const notes = [
    { id: 'new', title: 'Fresh note' },
    { id: 'old', title: 'Old note from first page' },
    { id: 'old', title: 'Old note from second page' },
  ] as Note[]

  assert.deepEqual(dedupeNotes(notes).map(note => note.title), [
    'Fresh note',
    'Old note from first page',
  ])
})
