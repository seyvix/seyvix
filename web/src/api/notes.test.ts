import test from 'node:test'
import assert from 'node:assert/strict'

import { cleanupTrash, fetchTrashNotes, MERGE_NOTES_ENABLED, mapBackendNote, restoreNote } from './notes.ts'

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

const baseNote = {
  id: 'note-1',
  slug: 'source-note',
  kind: 'complex',
  media_type: 'document',
  title: 'Source note',
  source_filename: 'source.pdf',
  taxonomy_category: {
    id: 'cat-1',
    name: 'Research',
    slug: 'research',
    path: 'projects/research',
  },
  tags: [{ id: 'tag-1', name: 'Auto tag', slug: 'auto-tag' }],
  is_favorite: false,
  sort_order: 10,
  created_at: '2026-05-01T08:00:00Z',
  updated_at: '2026-05-01T09:00:00Z',
  download_url: '/api/v1/notes/source-note/download',
  collection: null,
  assets: [
    {
      id: 'asset-1',
      role: 'original',
      media_type: 'document',
      filename: 'source.pdf',
      mime_type: 'application/pdf',
      size_bytes: 1024,
      url: '/api/v1/notes/source-note/asset/asset-1',
      text_content: null,
      thumbnail_url: '/api/v1/notes/source-note/asset/asset-1/thumbnail',
      thumbnail_text: 'Source preview text',
      markdown_url: '/api/v1/snapshots/artifacts/md-1',
      pdf_url: '/api/v1/snapshots/artifacts/pdf-1',
      html_url: '/api/v1/snapshots/artifacts/html-1',
    },
  ],
  items: [],
} as const

test('merge is temporarily disabled in the frontend contract', () => {
  assert.equal(MERGE_NOTES_ENABLED, false)
})

test('backend notes map taxonomy, tag slugs, and snapshot artifact views', () => {
  const note = mapBackendNote(baseNote)

  assert.equal(note.type, 'composite')
  assert.equal(note.taxonomyCategory?.path, 'projects/research')
  assert.deepEqual(note.tags[0], { id: 'tag-1', name: 'Auto tag', slug: 'auto-tag' })
  assert.equal(note.objects[0].snapshotViews?.map((view) => view.kind).join(','), 'thumbnail,markdown,pdf,html')
  assert.equal(note.objects[0].thumbnailText, 'Source preview text')
})

test('trash API fetches deleted notes, restores, and cleans up expired records', async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = []
  globalThis.fetch = async (input, init) => {
    calls.push({ url: String(input), init })
    if (String(input).endsWith('/cleanup')) return jsonResponse({ deleted_count: 2 })
    if (String(input).endsWith('/restore')) return jsonResponse(baseNote)
    return jsonResponse({ items: [baseNote] })
  }

  const notes = await fetchTrashNotes()
  const restored = await restoreNote('source-note')
  const cleanup = await cleanupTrash()

  assert.equal(notes[0].slug, 'source-note')
  assert.equal(restored.slug, 'source-note')
  assert.equal(cleanup.deletedCount, 2)
  assert.equal(calls[0].url, '/api/v1/notes/trash')
  assert.equal(calls[1].url, '/api/v1/notes/source-note/restore')
  assert.equal(calls[1].init?.method, 'POST')
  assert.equal(calls[2].url, '/api/v1/notes/trash/cleanup')
})
