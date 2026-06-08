import test from 'node:test'
import assert from 'node:assert/strict'

import { getObjectDisplayText, getObjectPreviewSource, shouldShowVideoPreviewOverlay } from './notePreview.ts'

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

test('text preview renders telegram custom emoji markers as fallback emoji', () => {
  assert.equal(
    getObjectDisplayText({
      id: 'asset-1',
      type: 'text',
      content: '{{tg_emoji:5280586677532774817|⚡️}} Важно',
      createdAt: '2026-05-01T10:00:00Z',
    }),
    '⚡️ Важно',
  )
})

test('video preview overlay is shown only for video objects', () => {
  assert.equal(shouldShowVideoPreviewOverlay({
    id: 'video-1',
    type: 'video',
    content: '/api/v1/notes/note/asset/video',
    thumbnailUrl: '/api/v1/notes/note/asset/video/thumbnail',
    createdAt: '2026-05-01T10:00:00Z',
  }), true)
  assert.equal(shouldShowVideoPreviewOverlay({
    id: 'image-1',
    type: 'image',
    content: '/api/v1/notes/note/asset/image',
    thumbnailUrl: '/api/v1/notes/note/asset/image/thumbnail',
    createdAt: '2026-05-01T10:00:00Z',
  }), false)
})
