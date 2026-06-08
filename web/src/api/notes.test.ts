import test from 'node:test'
import assert from 'node:assert/strict'

import { fetchNotes, reorderNotes, updateNote } from './notes.ts'

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

test('fetchNotes returns note items from the backend response', async () => {
  globalThis.fetch = async () => jsonResponse({
    items: [{ id: 'note-1', slug: 'first', title: 'First note' }],
  })

  const notes = await fetchNotes()

  assert.equal(notes.length, 1)
  assert.equal(notes[0].slug, 'first')
})

test('fetchNotes forwards abort signal to the request', async () => {
  const controller = new AbortController()
  let capturedSignal: AbortSignal | undefined
  globalThis.fetch = async (_input, init) => {
    capturedSignal = init?.signal ?? undefined
    return jsonResponse({ items: [] })
  }

  await fetchNotes({ search: 'Valheim' }, controller.signal)

  assert.equal(capturedSignal, controller.signal)
})

test('fetchNotes serializes extended note filters', async () => {
  let capturedUrl = ''
  globalThis.fetch = async (input) => {
    capturedUrl = String(input)
    return jsonResponse({ items: [] })
  }

  await fetchNotes({
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

  const url = new URL(capturedUrl)
  assert.equal(url.searchParams.get('search'), 'new game')
  assert.deepEqual(url.searchParams.getAll('types'), ['video', 'pdf'])
  assert.deepEqual(url.searchParams.getAll('sources'), ['telegram'])
  assert.equal(url.searchParams.get('favorite'), 'true')
  assert.equal(url.searchParams.get('created_after'), '2026-05-01')
  assert.equal(url.searchParams.get('created_before'), '2026-06-01')
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
