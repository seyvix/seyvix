import test from 'node:test'
import assert from 'node:assert/strict'

import { getObjectDisplayText, getObjectPreviewSource } from './notePreview.ts'

test('card preview prefers generated thumbnail over original asset', () => {
  assert.equal(
    getObjectPreviewSource({
      id: 'asset-1',
      type: 'image',
      content: '/api/v1/notes/note/asset/original',
      thumbnailUrl: '/api/v1/notes/note/asset/thumb',
      createdAt: '2026-05-01T10:00:00Z',
    }),
    '/api/v1/notes/note/asset/thumb',
  )
})

test('text preview prefers generated snapshot text and truncates it', () => {
  assert.equal(
    getObjectDisplayText({
      id: 'asset-1',
      type: 'text',
      content: 'full original text that is too long',
      thumbnailText: 'short generated preview',
      createdAt: '2026-05-01T10:00:00Z',
    }, 12),
    'short genera...',
  )
})
