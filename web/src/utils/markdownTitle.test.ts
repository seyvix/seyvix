import test from 'node:test'
import assert from 'node:assert/strict'

import { makeMarkdownTitle } from './markdownTitle.ts'

test('markdown title ignores formatting and picks first meaningful line', () => {
  assert.equal(makeMarkdownTitle('\n# **Important** note\n\nBody'), 'Important note')
  assert.equal(makeMarkdownTitle('- [ ] first task'), 'first task')
  assert.equal(
    makeMarkdownTitle('\n# {{tg_emoji:5280586677532774817|⚡}} **Важно**\n\nBody'),
    '⚡ Важно',
  )
})
