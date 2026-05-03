import { http, HttpResponse } from 'msw'
import { folderFixtures } from '../fixtures/folders'

const folders = [...folderFixtures]

function toBackendFolder(folder: (typeof folderFixtures)[number]): unknown {
  return {
    id: folder.id,
    slug: folder.slug,
    name: folder.name,
    path: folder.path,
    direct_count: folder.directCount,
    total_count: folder.totalCount,
    children: folder.children.map(toBackendFolder),
  }
}

export const folderHandlers = [
  http.get('/api/v1/folders', () => {
    return HttpResponse.json({ items: folders.map(toBackendFolder) })
  }),

  http.get('/api/v1/folders/:path+', ({ params }) => {
    const path = Array.isArray(params.path) ? params.path.join('/') : params.path
    const folder = folders
      .flatMap(root => [root, ...root.children])
      .find(f => f.path === path)
    if (!folder) return HttpResponse.json({ error: 'Not found' }, { status: 404 })
    return HttpResponse.json({
      folder: toBackendFolder(folder),
      tags: [{ id: `${folder.id}-tag`, name: 'research', slug: 'research' }],
      notes: [],
    })
  }),

  http.post('/api/v1/taxonomy/content/inbox/reclassify', () => {
    return HttpResponse.json({ enqueued_count: 0 }, { status: 202 })
  }),
]
