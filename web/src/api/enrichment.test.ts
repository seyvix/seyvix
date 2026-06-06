import test from 'node:test'
import assert from 'node:assert/strict'

import {
  createOrFindTag,
  fetchSnapshotArtifacts,
  reprocessSnapshotMarkdown,
} from './enrichment.ts'

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

test('fetchSnapshotArtifacts returns artifact items from the backend response', async () => {
  globalThis.fetch = async () => jsonResponse({
    items: [{ id: 'artifact-1', artifact_type: 'markdown', status: 'ready' }],
  })

  const artifacts = await fetchSnapshotArtifacts('object-1')

  assert.equal(artifacts.length, 1)
  assert.equal(artifacts[0].id, 'artifact-1')
})

test('reprocessSnapshotMarkdown surfaces backend queueing errors', async () => {
  globalThis.fetch = async () => jsonResponse(
    { error: { message: 'Snapshot asset is not ready.' } },
    { status: 409 },
  )

  await assert.rejects(
    () => reprocessSnapshotMarkdown('object-1', 'asset-1'),
    /Snapshot asset is not ready/,
  )
})

test('createOrFindTag returns an existing tag after a create conflict', async () => {
  let createAttempts = 0
  let lookupAttempts = 0
  globalThis.fetch = async (input, init) => {
    if (String(input) === '/api/v1/tags' && init?.method === 'POST') {
      createAttempts += 1
      return jsonResponse({ error: { message: 'Tag already exists.' } }, { status: 409 })
    }
    lookupAttempts += 1
    if (lookupAttempts === 1) {
      return jsonResponse([])
    }
    return jsonResponse([{ id: 'tag-1', name: 'Manual', slug: 'manual' }])
  }

  const tag = await createOrFindTag('Manual')

  assert.equal(tag.id, 'tag-1')
  assert.equal(createAttempts, 1)
  assert.equal(lookupAttempts, 2)
})
