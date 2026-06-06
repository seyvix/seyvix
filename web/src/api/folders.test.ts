import test from 'node:test'
import assert from 'node:assert/strict'

import {
  fetchCategoryProfile,
  suggestCategoryProfile,
  updateCategoryProfile,
} from './folders.ts'

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

test('missing category profile is treated as an editable empty profile', async () => {
  globalThis.fetch = async () => new Response(null, { status: 404 })

  const profile = await fetchCategoryProfile('cat-1')

  assert.equal(profile.categoryId, 'cat-1')
  assert.equal(profile.summary, null)
  assert.deepEqual(profile.keywords, [])
  assert.deepEqual(profile.positiveExamples, [])
  assert.deepEqual(profile.negativeExamples, [])
})

test('category profile operations report backend rejections', async () => {
  globalThis.fetch = async () => jsonResponse(
    { message: 'Profile editing is disabled.' },
    { status: 403 },
  )

  await assert.rejects(
    () => updateCategoryProfile('cat-1', {
      summary: 'Manual summary',
      keywords: ['ai'],
      positiveExamples: ['Models'],
      negativeExamples: [],
    }),
    /Failed to update category profile/,
  )
  await assert.rejects(
    () => suggestCategoryProfile('cat-1', 'Добавить LLM и инференс.'),
    /Failed to suggest category profile/,
  )
})
