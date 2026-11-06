import test from 'node:test'
import assert from 'node:assert/strict'

import { slugify } from './slugify.ts'

test('slugify transliterates Cyrillic and strips punctuation', () => {
  assert.equal(slugify('  Игры и Стратегии! '), 'igry-i-strategii')
  assert.equal(slugify('Café déjà vu'), 'cafe-deja-vu')
  assert.equal(slugify('!!!'), 'category')
})
