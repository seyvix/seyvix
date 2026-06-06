import assert from 'node:assert/strict'
import { test } from 'node:test'

import { shouldRenderBeforeAuthRefresh, shouldSkipInitialRefresh } from './authBootstrap.ts'

test('initial refresh is skipped on the Telegram callback route', () => {
  assert.equal(shouldSkipInitialRefresh('/auth/callback'), true)
  assert.equal(shouldSkipInitialRefresh('/notes'), false)
  assert.equal(shouldSkipInitialRefresh('/auth'), false)
})

test('guest auth routes can render before auth refresh completes', () => {
  assert.equal(shouldRenderBeforeAuthRefresh('/auth'), true)
  assert.equal(shouldRenderBeforeAuthRefresh('/auth/callback'), true)
  assert.equal(shouldRenderBeforeAuthRefresh('/notes'), false)
})
