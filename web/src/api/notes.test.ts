import test from 'node:test'
import assert from 'node:assert/strict'

import { fetchNoteChanges, fetchNotesPage, reorderNotes, updateNote } from './notes.ts'
import { setAccessToken } from '../lib/apiClient.ts'

setAccessToken('test-token')

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

test('fetchNotesPage returns note items from the backend response', async () => {
  globalThis.fetch = async () => jsonResponse({
    items: [{ id: 'note-1', slug: 'first', title: 'First note' }],
  })

  const page = await fetchNotesPage()

  assert.equal(page.items.length, 1)
  assert.equal(page.items[0].slug, 'first')
  assert.equal(page.nextOffset, null)
})

test('fetchNotesPage forwards abort signal to the request', async () => {
  const controller = new AbortController()
  let capturedSignal: AbortSignal | undefined
  globalThis.fetch = async (_input, init) => {
    capturedSignal = init?.signal ?? undefined
    return jsonResponse({ items: [] })
  }

  await fetchNotesPage({ search: 'Valheim' }, controller.signal)

  assert.equal(capturedSignal, controller.signal)
})

test('fetchNotesPage serializes extended note filters', async () => {
  let capturedUrl = ''
  globalThis.fetch = async (input) => {
    capturedUrl = String(input)
    return jsonResponse({ items: [] })
  }

  await fetchNotesPage({
    search: 'new game',
    searchMode: 'hybrid',
    tags: ['games'],
    folders: ['Games/Strategy'],
    contentTypes: ['video', 'pdf'],
    sources: ['telegram'],
    favorite: true,
    createdAfter: '2026-05-01',
    createdBefore: '2026-06-01',
  })

  const url = new URL(capturedUrl, 'http://localhost')
  assert.equal(url.searchParams.get('view'), 'card')
  assert.equal(url.searchParams.get('search'), 'new game')
  assert.deepEqual(url.searchParams.getAll('types'), ['video', 'pdf'])
  assert.deepEqual(url.searchParams.getAll('sources'), ['telegram'])
  assert.equal(url.searchParams.get('favorite'), 'true')
  assert.equal(url.searchParams.get('created_after'), '2026-05-01')
  assert.equal(url.searchParams.get('created_before'), '2026-06-01')
})

test('fetchNotesPage serializes pagination and returns next offset', async () => {
  let capturedUrl = ''
  globalThis.fetch = async (input) => {
    capturedUrl = String(input)
    return jsonResponse({
      items: [{ id: 'note-2', slug: 'second', title: 'Second note' }],
      nextOffset: 120,
    })
  }

  const page = await fetchNotesPage({ sort: 'custom' }, undefined, { limit: 60, offset: 60 })

  const url = new URL(capturedUrl, 'http://localhost')
  assert.equal(url.searchParams.get('view'), 'card')
  assert.equal(url.searchParams.get('sort'), 'custom')
  assert.equal(url.searchParams.get('limit'), '60')
  assert.equal(url.searchParams.get('offset'), '60')
  assert.equal(page.items[0].slug, 'second')
  assert.equal(page.nextOffset, 120)
})

test('reorderNotes reports backend failures', async () => {
  globalThis.fetch = async () => new Response(null, { status: 500 })

  await assert.rejects(
    () => reorderNotes([{ slug: 'first', position: 10 }]),
    /Failed to reorder notes/,
  )
})

test('updateNote serializes edited text objects for the backend patch contract', async () => {
  let capturedBody = ''
  globalThis.fetch = async (_input, init) => {
    capturedBody = String(init?.body ?? '')
    return jsonResponse({ id: 'note-1', slug: 'note-1', title: 'Renamed', objects: [] })
  }

  await updateNote('note-1', {
    title: 'Renamed',
    objects: [{
      id: 'text-1',
      type: 'text',
      content: 'Updated **markdown**',
      createdAt: '2026-06-09T00:00:00Z',
    }],
  })

  assert.deepEqual(JSON.parse(capturedBody), {
    title: 'Renamed',
    text: 'Updated **markdown**',
  })
})

test('fetchNoteChanges sends the cursor and maps the feed payload', async () => {
  let capturedUrl = ''
  globalThis.fetch = async (input) => {
    capturedUrl = String(input)
    return jsonResponse({
      cursor: 'c2',
      notes: [{ id: 'n1', slug: 'n1', title: 'Changed', processing: true }],
      removed_ids: ['gone'],
      reset: false,
      has_more: true,
    })
  }

  const changes = await fetchNoteChanges('2026-11-06T10:00:00+00:00')

  const url = new URL(capturedUrl, 'http://localhost')
  assert.equal(url.pathname, '/api/v1/notes/changes')
  assert.equal(url.searchParams.get('since'), '2026-11-06T10:00:00+00:00')
  assert.equal(changes.cursor, 'c2')
  assert.equal(changes.notes[0].processing, true)
  assert.deepEqual(changes.removedIds, ['gone'])
  assert.equal(changes.reset, false)
  assert.equal(changes.hasMore, true)
})

test('fetchNoteChanges without a cursor omits since', async () => {
  let capturedUrl = ''
  globalThis.fetch = async (input) => {
    capturedUrl = String(input)
    return jsonResponse({ cursor: 'c1', notes: [], removed_ids: [], reset: true })
  }

  const changes = await fetchNoteChanges(null)

  assert.equal(capturedUrl, '/api/v1/notes/changes')
  assert.equal(changes.reset, true)
})
