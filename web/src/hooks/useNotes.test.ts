import test from 'node:test'
import assert from 'node:assert/strict'

import { notesQueryKey } from './useNotes.ts'

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
