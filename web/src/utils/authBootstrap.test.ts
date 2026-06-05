import assert from 'node:assert/strict'
import { test } from 'node:test'

import { shouldSkipInitialRefresh } from './authBootstrap.ts'

test('initial refresh is skipped on the Telegram callback route', () => {
  assert.equal(shouldSkipInitialRefresh('/auth/callback'), true)
  assert.equal(shouldSkipInitialRefresh('/notes'), false)
  assert.equal(shouldSkipInitialRefresh('/auth'), false)
})
