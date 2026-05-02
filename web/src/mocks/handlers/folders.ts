import { http, HttpResponse } from 'msw'
import { folderFixtures } from '../fixtures/folders'

const folders = [...folderFixtures]

export const folderHandlers = [
  http.get('/api/folders', () => {
    return HttpResponse.json(folders)
  }),

  http.get('/api/folders/:slug', ({ params }) => {
    const folder = folders.find(f => f.slug === params.slug)
    if (!folder) return HttpResponse.json({ error: 'Not found' }, { status: 404 })
    return HttpResponse.json(folder)
  }),
]
