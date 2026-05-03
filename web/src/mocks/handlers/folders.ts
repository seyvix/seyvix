import { http, HttpResponse } from 'msw'
import { folderFixtures } from '../fixtures/folders'

const folders = [...folderFixtures]

export const folderHandlers = [
  http.get('/api/v1/folders', () => {
    return HttpResponse.json({ items: folders })
  }),

  http.get('/api/v1/folders/:path+', ({ params }) => {
    const path = Array.isArray(params.path) ? params.path.join('/') : params.path
    const folder = folders
      .flatMap(root => [root, ...root.children])
      .find(f => f.path === path)
    if (!folder) return HttpResponse.json({ error: 'Not found' }, { status: 404 })
    return HttpResponse.json({
      folder,
      tags: [{ id: `${folder.id}-tag`, name: 'research', slug: 'research' }],
      notes: [],
    })
  }),
]
