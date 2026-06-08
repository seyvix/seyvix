import test from 'node:test'
import assert from 'node:assert/strict'

import { moveSlashMenuSelection } from './slashMenuNavigation.ts'

test('moveSlashMenuSelection wraps through slash command options', () => {
  assert.equal(moveSlashMenuSelection(0, 4, 1), 1)
  assert.equal(moveSlashMenuSelection(3, 4, 1), 0)
  assert.equal(moveSlashMenuSelection(0, 4, -1), 3)
})

test('moveSlashMenuSelection clamps stale selected indexes before moving', () => {
  assert.equal(moveSlashMenuSelection(8, 3, 1), 0)
  assert.equal(moveSlashMenuSelection(-2, 3, -1), 2)
  assert.equal(moveSlashMenuSelection(2, 0, 1), 0)
})
