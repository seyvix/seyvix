import test from 'node:test'
import assert from 'node:assert/strict'

import {
  archiveCategory,
  createCategory,
  deleteCategory,
  fetchCategoryProfile,
  fetchTaxonomySettings,
  mapBackendFolder,
  mapBackendFolderDetail,
  suggestCategoryProfile,
  updateCategory,
  updateCategoryProfile,
  updateTaxonomySettings,
} from './folders.ts'

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

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

test('category profile API maps settings, manual saves and LLM drafts', async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = []
  globalThis.fetch = async (input, init) => {
    calls.push({ url: String(input), init })
    if (String(input) === '/api/v1/taxonomy/settings' && init?.method === 'PATCH') {
      return jsonResponse({
        owner_user_id: 'user-1',
        category_profile_editing_enabled: true,
        trash_enabled: true,
        trash_retention_days: 30,
      })
    }
    if (String(input) === '/api/v1/taxonomy/settings') {
      return jsonResponse({
        owner_user_id: 'user-1',
        category_profile_editing_enabled: false,
        trash_enabled: true,
        trash_retention_days: 30,
      })
    }
    if (String(input).endsWith('/profile/improve')) {
      return jsonResponse({
        summary: 'Improved summary',
        keywords: ['ai', 'llm'],
        positive_examples: ['Inference'],
        negative_examples: ['Groceries'],
        reasoning: 'Clearer boundary.',
      })
    }
    return jsonResponse({
      id: 'profile-1',
      category_id: 'cat-1',
      summary: 'Manual summary',
      keywords: ['ai'],
      positive_examples: ['Models'],
      negative_examples: [],
      created_at: '2026-05-03T10:00:00Z',
      updated_at: '2026-05-03T10:05:00Z',
    })
  }

  const settings = await fetchTaxonomySettings()
  await updateTaxonomySettings({ categoryProfileEditingEnabled: true })
  const profile = await fetchCategoryProfile('cat-1')
  await updateCategoryProfile('cat-1', profile)
  const draft = await suggestCategoryProfile('cat-1', 'Добавить LLM и инференс.')

  assert.equal(settings.categoryProfileEditingEnabled, false)
  assert.equal(profile.categoryId, 'cat-1')
  assert.equal(draft.keywords[1], 'llm')
  assert.equal(calls[1].init?.body, JSON.stringify({ category_profile_editing_enabled: true }))
  assert.equal(calls[3].init?.body, JSON.stringify({
    summary: 'Manual summary',
    keywords: ['ai'],
    positive_examples: ['Models'],
    negative_examples: [],
  }))
  assert.equal(calls[4].init?.body, JSON.stringify({ user_guidance: 'Добавить LLM и инференс.' }))
})

test('category CRUD API sends taxonomy category payloads', async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = []
  globalThis.fetch = async (input, init) => {
    calls.push({ url: String(input), init })
    return jsonResponse({
      id: 'cat-2',
      name: 'Inference',
      slug: 'inference',
      path: 'ai/inference',
      direct_count: 0,
      total_count: 0,
      children: [],
    }, init?.method === 'POST' ? { status: 201 } : {})
  }

  await createCategory({ name: 'Inference', parentId: 'cat-1', description: 'Model serving.' })
  await updateCategory('cat-2', { name: 'LLM inference', description: 'Serving models.' })
  await archiveCategory('cat-2')
  await deleteCategory('cat-2', {
    deleteNotes: true,
    confirmCategoryName: 'LLM inference',
    confirmDeleteNotesText: 'DELETE_NOTES',
  })

  assert.equal(calls[0].url, '/api/v1/taxonomy/categories')
  assert.equal(calls[0].init?.method, 'POST')
  assert.equal(calls[0].init?.body, JSON.stringify({
    parent_id: 'cat-1',
    slug: 'inference',
    name: 'Inference',
    description: 'Model serving.',
    sort_order: 100,
  }))
  assert.equal(calls[1].url, '/api/v1/taxonomy/categories/cat-2')
  assert.equal(calls[1].init?.method, 'PATCH')
  assert.equal(calls[1].init?.body, JSON.stringify({
    name: 'LLM inference',
    description: 'Serving models.',
  }))
  assert.equal(calls[2].url, '/api/v1/taxonomy/categories/cat-2')
  assert.equal(calls[2].init?.method, 'DELETE')
  assert.equal(calls[3].url, '/api/v1/taxonomy/categories/cat-2/delete')
  assert.equal(calls[3].init?.method, 'POST')
  assert.equal(calls[3].init?.body, JSON.stringify({
    delete_notes: true,
    confirm_category_name: 'LLM inference',
    confirm_delete_notes_text: 'DELETE_NOTES',
  }))
})
