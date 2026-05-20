import test from 'node:test'
import assert from 'node:assert/strict'

import { fetchNotes, reorderNotes } from './notes.ts'

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

test('fetchNotes sends custom sort when requested', async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = []
  globalThis.fetch = async (input, init) => {
    calls.push({ url: String(input), init })
    return jsonResponse({ items: [] })
  }

  await fetchNotes({ sort: 'custom', search: 'grid' })

  const url = new URL(calls[0].url)
  assert.equal(url.pathname, '/api/v1/notes')
  assert.equal(url.searchParams.get('sort'), 'custom')
  assert.equal(url.searchParams.get('search'), 'grid')
})

test('fetchNotes sends selected search mode when searching', async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = []
  globalThis.fetch = async (input, init) => {
    calls.push({ url: String(input), init })
    return jsonResponse({ items: [] })
  }

  await fetchNotes({ search: 'semantic notes', searchMode: 'semantic' })

  const url = new URL(calls[0].url)
  assert.equal(url.pathname, '/api/v1/notes')
  assert.equal(url.searchParams.get('search'), 'semantic notes')
  assert.equal(url.searchParams.get('search_mode'), 'semantic')
})

test('reorderNotes sends backend order payload', async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = []
  globalThis.fetch = async (input, init) => {
    calls.push({ url: String(input), init })
    return new Response(null, { status: 204 })
  }

  await reorderNotes([
    { slug: 'second', position: 10 },
    { slug: 'first', position: 20 },
  ])

  assert.equal(calls[0].url, '/api/v1/notes/order')
  assert.equal(calls[0].init?.method, 'PATCH')
  assert.equal(calls[0].init?.body, JSON.stringify({
    items: [
      { slug: 'second', position: 10 },
      { slug: 'first', position: 20 },
    ],
  }))
})
