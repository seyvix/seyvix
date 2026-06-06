import test from 'node:test'
import assert from 'node:assert/strict'

import { configureApiClient } from '../lib/apiClient.ts'
import {
  authenticatedBlobUrl,
  cachedAuthenticatedBlobUrl,
  openAuthenticatedAsset,
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

test('protected assets open from an authenticated object URL', async () => {
  const events: string[] = []
  const openedWindow = { location: { href: 'about:blank' }, opener: {}, close: () => {} }
  const originalWindow = globalThis.window

  configureApiClient({
    getToken: () => 'access-token',
    setToken: () => {},
    onUnauthenticated: () => {},
  })
  globalThis.fetch = async (input, init) => {
    events.push(`fetch:${String(input)}:${new Headers(init?.headers).get('Authorization')}`)
    return new Response(new Blob(['image'], { type: 'image/jpeg' }), { status: 200 })
  }
  globalThis.window = {
    open: (url?: string, target?: string, features?: string) => {
      events.push(`open:${url ?? ''}:${target ?? ''}:${features ?? ''}`)
      return openedWindow
    },
  } as unknown as Window & typeof globalThis

  try {
    const objectUrl = await openAuthenticatedAsset('/api/v1/notes/note/asset/image')

    assert.match(objectUrl, /^blob:/)
    assert.equal(openedWindow.location.href, objectUrl)
    assert.equal(openedWindow.opener, null)
    assert.deepEqual(events, [
      'open::_blank:',
      'fetch:/api/v1/notes/note/asset/image:Bearer access-token',
    ])
  } finally {
    globalThis.window = originalWindow
  }
})
