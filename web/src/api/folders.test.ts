import test from 'node:test'
import assert from 'node:assert/strict'

import { mapBackendFolder, mapBackendFolderDetail } from './folders.ts'

const backendFolder = {
  id: 'cat-root',
  name: 'Research',
  slug: 'research',
  path: 'work/research',
  children: [
    {
      id: 'cat-child',
      name: 'LLM',
      slug: 'llm',
      path: 'work/research/llm',
      direct_count: 2,
      total_count: 2,
      children: [],
    },
  ],
  direct_count: 1,
  total_count: 3,
}

test('backend folder tree maps category paths through every level', () => {
  const category = mapBackendFolder(backendFolder)

  assert.equal(category.path, 'work/research')
  assert.equal(category.directCount, 1)
  assert.equal(category.totalCount, 3)
  assert.equal(category.children[0].parentId, 'cat-root')
  assert.equal(category.children[0].path, 'work/research/llm')
  assert.equal(category.children[0].totalCount, 2)
})

test('backend folder detail maps selected category tags and note summaries', () => {
  const detail = mapBackendFolderDetail({
    folder: backendFolder,
    tags: [{ id: 'tag-1', name: 'machine-learning', slug: 'machine-learning' }],
    notes: [
      {
        id: 'note-1',
        slug: 'transformer-notes',
        title: 'Transformer notes',
        taxonomy_category: {
          id: 'cat-child',
          name: 'LLM',
          slug: 'llm',
          path: 'work/research/llm',
        },
        created_at: '2026-05-02T10:00:00Z',
        updated_at: '2026-05-02T11:00:00Z',
      },
    ],
  })

  assert.equal(detail.category.path, 'work/research')
  assert.deepEqual(detail.tags, [{ id: 'tag-1', name: 'machine-learning', slug: 'machine-learning' }])
  assert.equal(detail.notes[0].slug, 'transformer-notes')
  assert.equal(detail.notes[0].taxonomyCategory?.path, 'work/research/llm')
  assert.equal(detail.notes[0].updatedAt, '2026-05-02T11:00:00Z')
})
