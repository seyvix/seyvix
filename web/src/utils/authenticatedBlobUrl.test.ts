import test from 'node:test'
import assert from 'node:assert/strict'

import { configureApiClient, refreshApiToken } from '../lib/apiClient.ts'
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

test('concurrent protected media requests share one fetch and one object URL', async () => {
  const calls: string[] = []
  configureApiClient({
    getToken: () => 'access-token',
    setToken: () => {},
    onUnauthenticated: () => {},
  })
  globalThis.fetch = async (input) => {
    calls.push(String(input))
    await new Promise(resolve => setTimeout(resolve, 1))
    return new Response(new Blob(['image'], { type: 'image/png' }), { status: 200 })
  }

  const src = '/api/v1/notes/note/asset/image'
  const [first, second, third] = await Promise.all([
    authenticatedBlobUrl(src),
    authenticatedBlobUrl(src),
    authenticatedBlobUrl(src),
  ])

  assert.match(first, /^blob:/)
  assert.equal(second, first)
  assert.equal(third, first)
  assert.equal(cachedAuthenticatedBlobUrl(src), first)
  assert.deepEqual(calls, [src])
})

test('protected media waits for an in-flight refresh before first fetch', async () => {
  let token: string | null = null
  const calls: Array<{ url: string; authorization: string | null }> = []

  configureApiClient({
    getToken: () => token,
    setToken: (nextToken) => { token = nextToken },
    onUnauthenticated: () => {},
  })

  globalThis.fetch = async (input, init) => {
    const url = String(input)
    calls.push({ url, authorization: new Headers(init?.headers).get('Authorization') })

    if (url === '/api/v1/auth/refresh') {
      await new Promise(resolve => setTimeout(resolve, 1))
      return Response.json({
        access_token: 'fresh-access-token',
        token_type: 'bearer',
        user: { id: 'u1', display_name: 'User', is_active: true },
      })
    }

    return new Response(new Blob(['image'], { type: 'image/png' }), { status: 200 })
  }

  const refresh = refreshApiToken()
  const objectUrl = await authenticatedBlobUrl('/api/v1/notes/note/asset/after-refresh')
  await refresh

  assert.match(objectUrl, /^blob:/)
  assert.deepEqual(calls, [
    { url: '/api/v1/auth/refresh', authorization: null },
    { url: '/api/v1/notes/note/asset/after-refresh', authorization: 'Bearer fresh-access-token' },
  ])
})

test('protected media refreshes before the first fetch when no token is loaded', async () => {
  let token: string | null = null
  const calls: Array<{ url: string; authorization: string | null }> = []

  configureApiClient({
    getToken: () => token,
    setToken: (nextToken) => { token = nextToken },
    onUnauthenticated: () => {},
  })

  globalThis.fetch = async (input, init) => {
    const url = String(input)
    calls.push({ url, authorization: new Headers(init?.headers).get('Authorization') })

    if (url === '/api/v1/auth/refresh') {
      return Response.json({
        access_token: 'fresh-access-token',
        token_type: 'bearer',
        user: { id: 'u1', display_name: 'User', is_active: true },
      })
    }

    return new Response(new Blob(['image'], { type: 'image/png' }), { status: 200 })
  }

  const objectUrl = await authenticatedBlobUrl('/api/v1/notes/note/asset/no-token-yet')

  assert.match(objectUrl, /^blob:/)
  assert.deepEqual(calls, [
    { url: '/api/v1/auth/refresh', authorization: null },
    { url: '/api/v1/notes/note/asset/no-token-yet', authorization: 'Bearer fresh-access-token' },
  ])
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
    const objectUrl = await openAuthenticatedAsset('/api/v1/notes/note/asset/open-image')

    assert.match(objectUrl, /^blob:/)
    assert.equal(openedWindow.location.href, objectUrl)
    assert.equal(openedWindow.opener, null)
    assert.deepEqual(events, [
      'open::_blank:',
      'fetch:/api/v1/notes/note/asset/open-image:Bearer access-token',
    ])
  } finally {
    globalThis.window = originalWindow
  }
})
