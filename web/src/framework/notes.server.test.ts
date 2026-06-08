import test from 'node:test'
import assert from 'node:assert/strict'
import { QueryClient } from '@tanstack/react-query'

import { prefetchNotesRoute } from './notes.server.ts'

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

test('prefetchNotesRoute requests card view notes for SSR payloads', async () => {
  const previousApiBase = process.env.SSR_API_BASE_URL
  process.env.SSR_API_BASE_URL = 'http://backend:8000'
  const capturedUrls: string[] = []
  globalThis.fetch = async (input) => {
    capturedUrls.push(String(input))
    if (String(input).includes('/search/capabilities')) {
      return jsonResponse({
        noteCount: 20,
        threshold: 10,
        unlockedModes: ['full_text', 'hybrid'],
        defaultMode: 'hybrid',
      })
    }
    return jsonResponse({ items: [] })
  }

  await prefetchNotesRoute(
    new QueryClient(),
    new Request('http://app.local/notes?search=pico'),
    'access-token',
  )

  const notesUrl = new URL(capturedUrls[1])
  assert.equal(notesUrl.pathname, '/api/v1/notes')
  assert.equal(notesUrl.searchParams.get('search'), 'pico')
  assert.equal(notesUrl.searchParams.get('view'), 'card')
  assert.equal(notesUrl.searchParams.get('limit'), '60')

  if (previousApiBase === undefined) delete process.env.SSR_API_BASE_URL
  else process.env.SSR_API_BASE_URL = previousApiBase
})
