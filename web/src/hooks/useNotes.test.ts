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
    },
  ])
  assert.notDeepEqual(
    notesQueryKey({ search: 'Valheim', searchMode: 'hybrid' }),
    notesQueryKey({ search: 'Stronghold', searchMode: 'hybrid' }),
  )
})
