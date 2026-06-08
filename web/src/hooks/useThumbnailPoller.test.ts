import test from 'node:test'
import assert from 'node:assert/strict'

import { shouldPollThumbnails } from './useThumbnailPoller.ts'
import type { Note } from '../types'

const BASE_NOTE: Note = {
  id: 'note-1',
  slug: 'note-1',
  type: 'simple',
  title: 'Note',
  cover: null,
  tags: [],
  folderId: null,
  objects: [],
  createdAt: '2026-06-09T00:00:00Z',
  updatedAt: '2026-06-09T00:00:00Z',
}

test('shouldPollThumbnails only polls enabled persisted documents without thumbnails', () => {
  const pendingDocument: Note = {
    ...BASE_NOTE,
    objects: [{
      id: 'asset-1',
      type: 'document',
      content: '/api/v1/notes/note-1/asset/asset-1',
      thumbnailUrl: null,
      createdAt: '2026-06-09T00:00:00Z',
    }],
  }

  assert.equal(shouldPollThumbnails([pendingDocument], true), true)
  assert.equal(shouldPollThumbnails([pendingDocument], false), false)
  assert.equal(shouldPollThumbnails([{ ...pendingDocument, isLocal: true }], true), false)
  assert.equal(shouldPollThumbnails([BASE_NOTE], true), false)
})
