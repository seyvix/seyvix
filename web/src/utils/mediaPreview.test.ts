import test from 'node:test'
import assert from 'node:assert/strict'

import type { NoteObject } from '../types'
import {
  canPreviewVideoCard,
  shouldActivateVideoPreview,
  videoPreviewWindow,
} from './mediaPreview.ts'

function videoObject(overrides: Partial<NoteObject> = {}): NoteObject {
  return {
    id: 'video-1',
    type: 'video',
    content: '/api/v1/notes/note/asset/video-1',
    thumbnailUrl: '/api/v1/notes/note/asset/video-1/thumbnail',
    createdAt: '2026-06-01T10:00:00Z',
    ...overrides,
  }
}

test('video card preview is available only for videos with a playable asset url', () => {
  assert.equal(canPreviewVideoCard(videoObject()), true)
  assert.equal(canPreviewVideoCard(videoObject({ content: '' })), false)
  assert.equal(canPreviewVideoCard({ ...videoObject(), type: 'image' }), false)
})

test('video preview activation follows the saved autoplay preference', () => {
  const object = videoObject()

  assert.equal(shouldActivateVideoPreview({
    object,
    isHovered: true,
    isInViewport: false,
    autoplayInViewport: false,
    reducedMotion: false,
  }), true)
  assert.equal(shouldActivateVideoPreview({
    object,
    isHovered: false,
    isInViewport: true,
    autoplayInViewport: false,
    reducedMotion: false,
  }), false)
  assert.equal(shouldActivateVideoPreview({
    object,
    isHovered: false,
    isInViewport: true,
    autoplayInViewport: true,
    reducedMotion: false,
  }), true)
})

test('video preview stays disabled when reduced motion is requested', () => {
  assert.equal(shouldActivateVideoPreview({
    object: videoObject(),
    isHovered: true,
    isInViewport: true,
    autoplayInViewport: true,
    reducedMotion: true,
  }), false)
})

test('video preview samples the first short window by default', () => {
  assert.deepEqual(videoPreviewWindow(48), { start: 0, duration: 8 })
  assert.deepEqual(videoPreviewWindow(4), { start: 0, duration: 4 })
})
