import test from 'node:test'
import assert from 'node:assert/strict'

import { htmlToMarkdown, makeMarkdownTitle, replaceBlobImageSources } from './markdownPaste.ts'

test('html paste is normalized to markdown formatting', () => {
  const markdown = htmlToMarkdown('<h1>Plan</h1><p><strong>Bold</strong> and <em>italic</em> <u>under</u> <a href="https://example.com">link</a></p><ul><li>One</li></ul>')

  assert.match(markdown, /^# Plan/)
  assert.match(markdown, /\*\*Bold\*\*/)
  assert.match(markdown, /_italic_/)
  assert.match(markdown, /<u>under<\/u>/)
  assert.match(markdown, /\[link\]\(https:\/\/example.com\)/)
  assert.match(markdown, /- One/)
})

test('blob image sources are replaced with stable markdown attachment names', () => {
  const markdown = replaceBlobImageSources('Intro\n\n![image](blob:http://localhost/image-1)', new Map([
    ['blob:http://localhost/image-1', 'pasted-image-1.png'],
  ]))

  assert.equal(markdown, 'Intro\n\n![pasted-image-1.png](pasted-image-1.png)')
})

test('markdown title ignores formatting and picks first meaningful line', () => {
  assert.equal(makeMarkdownTitle('\n# **Important** note\n\nBody'), 'Important note')
  assert.equal(makeMarkdownTitle('- [ ] first task'), 'first task')
  assert.equal(
    makeMarkdownTitle('\n# {{tg_emoji:5280586677532774817|⚡}} **Важно**\n\nBody'),
    '⚡ Важно',
  )
})
