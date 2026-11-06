import test from 'node:test'
import assert from 'node:assert/strict'

import { setAccessToken } from '../lib/apiClient.ts'
import { ApiError } from '../lib/apiError.ts'
import {
  authenticatedBlobUrl,
  cachedAuthenticatedBlobUrl,
  clearAuthenticatedBlobCache,
  openAuthenticatedAsset,
  retainAuthenticatedBlobUrl,
} from './authenticatedBlobUrl.ts'

function blobResponse(body = 'media', size = 0) {
  return new Response(new Blob([size ? 'x'.repeat(size) : body]), { status: 200 })
}

const originalRevoke = URL.revokeObjectURL
let revoked: string[] = []
URL.revokeObjectURL = (url: string) => {
  revoked.push(url)
  originalRevoke(url)
}

test.beforeEach(() => {
  clearAuthenticatedBlobCache()
  revoked = []
  setAccessToken('access-token')
})

test('protected assets are fetched with auth and cached as object URLs', async () => {
  const calls: Array<{ url: string; authorization: string | null }> = []
  globalThis.fetch = async (input, init) => {
    calls.push({ url: String(input), authorization: new Headers(init?.headers).get('Authorization') })
    return blobResponse()
  }

  const first = await authenticatedBlobUrl('/api/v1/notes/note/asset/audio')
  const second = await authenticatedBlobUrl('/api/v1/notes/note/asset/audio')

  assert.match(first, /^blob:/)
  assert.equal(second, first)
  assert.equal(cachedAuthenticatedBlobUrl('/api/v1/notes/note/asset/audio'), first)
  assert.deepEqual(calls, [{ url: '/api/v1/notes/note/asset/audio', authorization: 'Bearer access-token' }])
})

test('concurrent requests share one fetch and one object URL', async () => {
  const calls: string[] = []
  const gate = Promise.withResolvers<void>()
  globalThis.fetch = async (input) => {
    calls.push(String(input))
    await gate.promise
    return blobResponse()
  }

  const src = '/api/v1/notes/note/asset/image'
  const pending = [authenticatedBlobUrl(src), authenticatedBlobUrl(src), authenticatedBlobUrl(src)]
  gate.resolve()
  const urls = await Promise.all(pending)

  assert.equal(new Set(urls).size, 1)
  assert.deepEqual(calls, [src])
})

test('failed asset requests reject with an ApiError and are not cached', async () => {
  globalThis.fetch = async () => Response.json({ error: { code: 'not_found', message: 'Нет файла' } }, { status: 404 })

  await assert.rejects(
    () => authenticatedBlobUrl('/api/v1/notes/note/asset/missing'),
    (error: unknown) => error instanceof ApiError && error.status === 404 && error.message === 'Нет файла',
  )
  assert.equal(cachedAuthenticatedBlobUrl('/api/v1/notes/note/asset/missing'), null)
})

test('idle object URLs are revoked beyond the byte budget, retained ones never', async () => {
  globalThis.fetch = async () => blobResponse('', 40 * 1024 * 1024)

  const release = retainAuthenticatedBlobUrl('/a')
  const retained = await authenticatedBlobUrl('/a')
  const b = await authenticatedBlobUrl('/b')
  const c = await authenticatedBlobUrl('/c') // idle: /b + /c = 80 MB > 64 MB → LRU idle /b goes

  assert.deepEqual(revoked, [b])
  assert.equal(cachedAuthenticatedBlobUrl('/a'), retained) // also marks /a most recently used
  assert.equal(cachedAuthenticatedBlobUrl('/b'), null)

  release()
  await authenticatedBlobUrl('/d') // idle: /c, /a, /d = 120 MB → evict /c, then /a
  assert.deepEqual(revoked, [b, c, retained])
})

test('logout cleanup revokes every cached object URL', async () => {
  globalThis.fetch = async () => blobResponse()

  const url = await authenticatedBlobUrl('/api/v1/notes/note/asset/x')
  clearAuthenticatedBlobCache()

  assert.ok(revoked.includes(url))
  assert.equal(cachedAuthenticatedBlobUrl('/api/v1/notes/note/asset/x'), null)
})

test('protected assets open from an authenticated object URL', async () => {
  const events: string[] = []
  const openedWindow = { location: { href: 'about:blank' }, opener: {}, close: () => {} }
  const originalWindow = globalThis.window

  globalThis.fetch = async (input, init) => {
    events.push(`fetch:${String(input)}:${new Headers(init?.headers).get('Authorization')}`)
    return blobResponse()
  }
  globalThis.window = {
    open: (url?: string, target?: string) => {
      events.push(`open:${url ?? ''}:${target ?? ''}`)
      return openedWindow
    },
    setTimeout: () => 0,
  } as unknown as Window & typeof globalThis

  try {
    const objectUrl = await openAuthenticatedAsset('/api/v1/notes/note/asset/open-image')

    assert.equal(openedWindow.location.href, objectUrl)
    assert.equal(openedWindow.opener, null)
    assert.deepEqual(events, [
      'open::_blank',
      'fetch:/api/v1/notes/note/asset/open-image:Bearer access-token',
    ])
  } finally {
    globalThis.window = originalWindow
  }
})
