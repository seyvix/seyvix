import test from 'node:test'
import assert from 'node:assert/strict'

import { createAccessGrant, parseAccessTarget } from './account.ts'
import { setAccessToken } from '../lib/apiClient.ts'
import { ApiError } from '../lib/apiError.ts'

setAccessToken('test-token')

test('parseAccessTarget accepts ids, @usernames and t.me links', () => {
  assert.deepEqual(parseAccessTarget(' 123456789 '), { telegram_user_id: 123456789 })
  assert.deepEqual(parseAccessTarget('@Some_User'), { username: 'Some_User' })
  assert.deepEqual(parseAccessTarget('https://t.me/some_user'), { username: 'some_user' })
  assert.equal(parseAccessTarget('@abc'), null)
  assert.equal(parseAccessTarget('hello world'), null)
  assert.equal(parseAccessTarget(''), null)
})

test('createAccessGrant surfaces duplicates as a 409 ApiError', async () => {
  let body = ''
  globalThis.fetch = async (_input, init) => {
    body = String(init?.body)
    return Response.json({ error: { code: 'conflict', message: 'Already allowed' } }, { status: 409 })
  }

  await assert.rejects(
    () => createAccessGrant({ username: 'some_user', note: 'friend' }),
    (error: unknown) => error instanceof ApiError && error.status === 409,
  )
  assert.deepEqual(JSON.parse(body), { username: 'some_user', note: 'friend' })
})
