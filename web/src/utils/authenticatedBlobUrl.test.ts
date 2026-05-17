import test from 'node:test'
import assert from 'node:assert/strict'

import { configureApiClient } from '../lib/apiClient.ts'
import {
  authenticatedBlobUrl,
  cachedAuthenticatedBlobUrl,
} from './authenticatedBlobUrl.ts'

test('protected media assets are fetched with auth and cached as object URLs', async () => {
  const calls: Array<{ url: string; headers: Headers }> = []
  configureApiClient({
    getToken: () => 'access-token',
    setToken: () => {},
    onUnauthenticated: () => {},
  })
  globalThis.fetch = async (input, init) => {
    calls.push({ url: String(input), headers: new Headers(init?.headers) })
    return new Response(new Blob(['media'], { type: 'audio/ogg' }), { status: 200 })
  }

  const first = await authenticatedBlobUrl('/api/v1/notes/note/asset/audio')
  const second = await authenticatedBlobUrl('/api/v1/notes/note/asset/audio')

  assert.match(first, /^blob:/)
  assert.equal(second, first)
  assert.equal(cachedAuthenticatedBlobUrl('/api/v1/notes/note/asset/audio'), first)
  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, '/api/v1/notes/note/asset/audio')
  assert.equal(calls[0].headers.get('Authorization'), 'Bearer access-token')
})

