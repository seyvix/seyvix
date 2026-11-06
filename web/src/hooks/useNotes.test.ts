import test from 'node:test'
import assert from 'node:assert/strict'

import {
  dedupeNotes,
  normalizeNotesQueryData,
  notesQueryKey,
  applyNoteChangesToNotesQueryData,
  upsertNoteInNotesQueryData,
} from './useNotes.ts'
import type { Note, NotesPageResult } from '../types/index.ts'

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

test('normalizeNotesQueryData migrates legacy note arrays into infinite data', () => {
  const notes = [
    { id: 'first', slug: 'first', title: 'First note' },
  ] as Note[]

  const data = normalizeNotesQueryData(notes)

  assert.deepEqual(data, {
    pages: [{ items: notes, nextOffset: null }],
    pageParams: [0],
  })
})

test('upsertNoteInNotesQueryData preserves infinite data shape', () => {
  const oldNote = { id: 'old', slug: 'old', title: 'Old note' } as Note
  const updatedNote = { id: 'new', slug: 'new', title: 'Uploaded deck' } as Note
  const page: NotesPageResult = {
    items: [oldNote],
    nextOffset: 60,
  }

  const data = upsertNoteInNotesQueryData(
    { pages: [page], pageParams: [0] },
    updatedNote,
  )

  assert.equal(data.pages.length, 1)
  assert.deepEqual(data.pageParams, [0])
  assert.deepEqual(data.pages[0].items.map(note => note.id), ['new', 'old'])
  assert.equal(data.pages[0].nextOffset, 60)
})

test('upsertNoteInNotesQueryData updates an existing note without duplicating it', () => {
  const oldNote = { id: 'same', slug: 'same', title: 'Old title' } as Note
  const updatedNote = { id: 'same', slug: 'same', title: 'New title' } as Note

  const data = upsertNoteInNotesQueryData(
    { pages: [{ items: [oldNote], nextOffset: null }], pageParams: [0] },
    updatedNote,
  )

  assert.deepEqual(data.pages[0].items.map(note => note.title), ['New title'])
})

test('applyNoteChangesToNotesQueryData replaces, removes and (optionally) inserts cards', () => {
  const a = { id: 'a', slug: 'a', title: 'A', stableKey: 'local-a', searchMatches: [{ text: 'hit', score: 1 }] } as Note
  const b = { id: 'b', slug: 'b', title: 'B' } as Note
  const data = { pages: [{ items: [a, b], nextOffset: 60 }], pageParams: [0] }
  const changed = new Map([
    ['a', { id: 'a', slug: 'a', title: 'A2', searchMatches: [] } as unknown as Note],
    ['c', { id: 'c', slug: 'c', title: 'C' } as Note],
  ])

  const filtered = applyNoteChangesToNotesQueryData(data, changed, new Set(['b']), { insertNew: false })
  const filteredItems = (filtered as typeof data).pages[0].items
  assert.deepEqual(filteredItems.map(note => note.title), ['A2'])
  assert.equal(filteredItems[0].stableKey, 'local-a')
  assert.equal(filteredItems[0].searchMatches?.[0].text, 'hit')

  const home = applyNoteChangesToNotesQueryData(data, changed, new Set(), { insertNew: true })
  assert.deepEqual((home as typeof data).pages[0].items.map(note => note.id), ['c', 'a', 'b'])
  assert.equal((home as typeof data).pages[0].nextOffset, 60)
})

test('applyNoteChangesToNotesQueryData keeps identity when nothing applies', () => {
  const data = { pages: [{ items: [{ id: 'a', slug: 'a' } as Note], nextOffset: null }], pageParams: [0] }
  assert.equal(applyNoteChangesToNotesQueryData(data, new Map(), new Set(['zzz']), { insertNew: false }), data)
})
