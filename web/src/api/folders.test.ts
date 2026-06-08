import test from 'node:test'
import assert from 'node:assert/strict'

import {
  fetchCategoryProfile,
  mapBackendFolderDetail,
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

test('folder detail maps app-note dates and preview objects', () => {
  const detail = mapBackendFolderDetail({
    folder: {
      id: 'cat-1',
      name: 'Inbox',
      slug: 'inbox',
      path: 'inbox',
      direct_count: 1,
      total_count: 1,
    },
    tags: [],
    notes: [{
      id: 'note-1',
      slug: 'note-1',
      title: '',
      taxonomyCategory: {
        id: 'cat-1',
        name: 'Inbox',
        slug: 'inbox',
        path: 'inbox',
      },
      objects: [{
        id: 'obj-1',
        type: 'text',
        content: 'Preview text',
        createdAt: '2026-06-08T10:00:00Z',
      }],
      createdAt: '2026-06-08T10:00:00Z',
      updatedAt: '2026-06-08T11:00:00Z',
    }],
  })

  assert.equal(detail.notes[0].createdAt, '2026-06-08T10:00:00Z')
  assert.equal(detail.notes[0].updatedAt, '2026-06-08T11:00:00Z')
  assert.equal(detail.notes[0].taxonomyCategory?.path, 'inbox')
  assert.equal(detail.notes[0].objects[0].content, 'Preview text')
})
