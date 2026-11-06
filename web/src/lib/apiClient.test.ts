import assert from 'node:assert/strict'
import test from 'node:test'

import { apiFetch, onAuthLost, refreshSession, setAccessToken } from './apiClient.ts'
import { ApiError, accessDeniedInfo } from './apiError.ts'

const USER = {
  id: 'user-1',
  telegram_id: '100500',
  telegram_username: 'tester',
  telegram_photo_url: null,
  display_name: 'Tester',
  is_active: true,
  is_admin: false,
}

function tokens(accessToken: string) {
  return Response.json({ user: USER, access_token: accessToken, token_type: 'bearer' })
}

test('concurrent 401 responses share one refresh and retry with the fresh token', async () => {
  setAccessToken('expired-token')
  let refreshCalls = 0
  const gate = Promise.withResolvers<void>()
  const protectedAuth: Array<string | null> = []

  globalThis.fetch = async (input, init) => {
    if (String(input).endsWith('/auth/refresh')) {
      refreshCalls += 1
      await gate.promise
      return tokens('fresh-token')
    }
    const authorization = new Headers(init?.headers).get('Authorization')
    protectedAuth.push(authorization)
    if (protectedAuth.length === 2) gate.resolve()
    return new Response(null, { status: authorization === 'Bearer fresh-token' ? 200 : 401 })
  }

  const [first, second] = await Promise.all([apiFetch('/api/v1/notes'), apiFetch('/api/v1/folders')])

  assert.equal(first.status, 200)
  assert.equal(second.status, 200)
  assert.equal(refreshCalls, 1)
  assert.equal(protectedAuth.filter(value => value === 'Bearer fresh-token').length, 2)
})

test('a rejected refresh notifies auth-lost listeners once and does not retry', async () => {
  setAccessToken('expired-token')
  const lost: ApiError[] = []
  const unsubscribe = onAuthLost(error => lost.push(error))
  let calls = 0

  globalThis.fetch = async (input) => {
    calls += 1
    if (String(input).endsWith('/auth/refresh')) {
      return Response.json(
        { error: { code: 'access_denied', message: 'Нет доступа', details: [{ telegram_user_id: 42, username: 'bob' }] } },
        { status: 403 },
      )
    }
    return new Response(null, { status: 401 })
  }

  try {
    const res = await apiFetch('/api/v1/notes')
    assert.equal(res.status, 401)
    assert.equal(calls, 2)
    assert.equal(lost.length, 1)
    assert.deepEqual(accessDeniedInfo(lost[0]), { message: 'Нет доступа', telegramUserId: 42, username: 'bob' })

    // No token any more: the next request refreshes once and gives up without a second refresh.
    calls = 0
    await apiFetch('/api/v1/notes')
    assert.equal(calls, 2)
  } finally {
    unsubscribe()
  }
})

test('transient refresh failures keep the session (no auth-lost)', async () => {
  setAccessToken('expired-token')
  let lost = 0
  const unsubscribe = onAuthLost(() => { lost += 1 })
  globalThis.fetch = async (input) => (
    String(input).endsWith('/auth/refresh')
      ? new Response('bad gateway', { status: 502 })
      : new Response(null, { status: 401 })
  )

  try {
    const res = await apiFetch('/api/v1/notes')
    assert.equal(res.status, 401)
    assert.equal(lost, 0)
    await assert.rejects(refreshSession(), (error: unknown) => error instanceof ApiError && error.status === 502)
  } finally {
    unsubscribe()
  }
})
