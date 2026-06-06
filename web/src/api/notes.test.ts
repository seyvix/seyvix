import test from 'node:test'
import assert from 'node:assert/strict'

import { fetchNotes, reorderNotes } from './notes.ts'

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

test('reorderNotes reports backend failures', async () => {
  globalThis.fetch = async () => new Response(null, { status: 500 })

  await assert.rejects(
    () => reorderNotes([{ slug: 'first', position: 10 }]),
    /Failed to reorder notes/,
  )
})
