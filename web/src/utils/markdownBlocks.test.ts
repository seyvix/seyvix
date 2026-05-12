import test from 'node:test'
import assert from 'node:assert/strict'

import { parseMarkdownBlocks } from './markdownBlocks.ts'

test('markdown blocks parse headings, paragraphs and lists', () => {
  assert.deepEqual(parseMarkdownBlocks('# Title\n\nText **bold**\n\n- One\n- Two'), [
    { type: 'heading', level: 1, text: 'Title' },
    { type: 'paragraph', text: 'Text **bold**' },
    { type: 'bulletList', items: ['One', 'Two'] },
  ])
})

test('markdown blocks parse tasks, quotes, dividers and fenced code', () => {
  assert.deepEqual(parseMarkdownBlocks('- [x] Done\n- [ ] Later\n\n> Quote\n> More\n\n---\n\n```ts\nconst a = 1\n```'), [
    { type: 'taskList', items: [{ checked: true, text: 'Done' }, { checked: false, text: 'Later' }] },
    { type: 'blockquote', text: 'Quote\nMore' },
    { type: 'divider' },
    { type: 'code', language: 'ts', text: 'const a = 1' },
  ])
})
