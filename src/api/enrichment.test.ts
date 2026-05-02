import test from 'node:test'
import assert from 'node:assert/strict'

import {
  assignCategoryToContent,
  assignExistingTagToContent,
  createTaxonomyCategory,
  createTag,
  fetchContentTagSuggestions,
  fetchContentTagJobs,
  fetchSnapshotArtifacts,
  fetchTaxonomyClassificationJobs,
  triggerTaxonomyClassification,
} from './enrichment.ts'

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

test('snapshot artifact lookup uses the backend content_object_id filter', async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = []
  globalThis.fetch = async (input, init) => {
    calls.push({ url: String(input), init })
    return jsonResponse({ items: [] })
  }

  await fetchSnapshotArtifacts('object-1')

  assert.equal(calls[0].url, '/api/v1/snapshots/artifacts?content_object_id=object-1')
})

test('enrichment job lookups use backend job-list endpoints', async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = []
  globalThis.fetch = async (input, init) => {
    calls.push({ url: String(input), init })
    return jsonResponse({ items: [] })
  }

  await fetchContentTagJobs('object-1')
  await fetchTaxonomyClassificationJobs('object-1')

  assert.equal(calls[0].url, '/api/v1/content/object-1/tags/jobs')
  assert.equal(calls[1].url, '/api/v1/taxonomy/content/object-1/classification-jobs')
})

test('manual tag and taxonomy actions use backend payload shapes', async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = []
  globalThis.fetch = async (input, init) => {
    calls.push({ url: String(input), init })
    if (String(input) === '/api/v1/tags') {
      return jsonResponse({ id: 'tag-1', name: 'Manual', slug: 'manual' }, { status: 201 })
    }
    return jsonResponse({ id: 'assignment-1' }, { status: 201 })
  }

  await createTag('Manual')
  await createTaxonomyCategory('Research')
  await assignExistingTagToContent('object-1', 'tag-1')
  await assignCategoryToContent('object-1', 'cat-1')
  await triggerTaxonomyClassification('object-1')
  await fetchContentTagSuggestions('object-1')

  assert.equal(calls[0].url, '/api/v1/tags')
  assert.equal(calls[0].init?.method, 'POST')
  assert.equal(calls[1].url, '/api/v1/taxonomy/categories')
  assert.equal(calls[1].init?.body, JSON.stringify({ name: 'Research', slug: 'research', parent_id: null }))
  assert.equal(calls[2].url, '/api/v1/content/object-1/tags')
  assert.equal(calls[2].init?.body, JSON.stringify({ tag_id: 'tag-1' }))
  assert.equal(calls[3].url, '/api/v1/taxonomy/content/object-1/assignments')
  assert.equal(calls[3].init?.body, JSON.stringify({ category_id: 'cat-1' }))
  assert.equal(calls[4].url, '/api/v1/taxonomy/content/object-1/classify')
  assert.equal(calls[5].url, '/api/v1/content/object-1/tags/suggestions')
})
