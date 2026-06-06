import { strict as assert } from 'node:assert'
import { describe, test } from 'node:test'
import { normalizeSearchMode } from './searchMode.ts'
import type { SearchCapabilities } from '../api/search.ts'

const unlockedAll: SearchCapabilities = {
  noteCount: 25,
  threshold: 20,
  unlockedModes: ['full_text', 'semantic', 'hybrid'],
  defaultMode: 'hybrid',
}

const lockedVectors: SearchCapabilities = {
  noteCount: 8,
  threshold: 20,
  unlockedModes: ['full_text'],
  defaultMode: 'full_text',
}

describe('normalizeSearchMode', () => {
  test('keeps a mode that is in unlockedModes', () => {
    assert.equal(normalizeSearchMode('semantic', unlockedAll), 'semantic')
    assert.equal(normalizeSearchMode('full_text', lockedVectors), 'full_text')
  })

  test('falls back to defaultMode when the requested mode is locked', () => {
    assert.equal(normalizeSearchMode('hybrid', lockedVectors), 'full_text')
    assert.equal(normalizeSearchMode('semantic', lockedVectors), 'full_text')
  })

  test('treats null/undefined as "use default"', () => {
    assert.equal(normalizeSearchMode(null, unlockedAll), 'hybrid')
    assert.equal(normalizeSearchMode(undefined, lockedVectors), 'full_text')
  })

  test('treats an unknown string as "use default"', () => {
    // @ts-expect-error: deliberately invalid mode
    assert.equal(normalizeSearchMode('lexical', unlockedAll), 'hybrid')
  })
})
