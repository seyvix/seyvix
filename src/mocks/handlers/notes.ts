import { http, HttpResponse } from 'msw'
import { noteFixtures } from '../fixtures/notes'
import type { Note } from '../../types'

let notes = [...noteFixtures]

export const noteHandlers = [
  http.get('/api/notes', ({ request }) => {
    const url = new URL(request.url)
    const search = url.searchParams.get('search')?.toLowerCase()
    const tags = url.searchParams.get('tags')?.split(',').filter(Boolean)

    let result = notes
    if (search) {
      result = result.filter(n => n.title.toLowerCase().includes(search))
    }
    if (tags?.length) {
      result = result.filter(n => n.tags.some(t => tags.includes(t.name)))
    }
    return HttpResponse.json(result)
  }),

  http.get('/api/notes/:slug', ({ params }) => {
    const note = notes.find(n => n.slug === params.slug)
    if (!note) return HttpResponse.json({ error: 'Not found' }, { status: 404 })
    return HttpResponse.json(note)
  }),

  http.post('/api/notes', async ({ request }) => {
    const body = await request.json() as Partial<Note>
    const note: Note = {
      id: String(Date.now()),
      slug: (body.title ?? 'untitled').toLowerCase().replace(/\s+/g, '-'),
      type: body.type ?? 'simple',
      title: body.title ?? 'Untitled',
      cover: null,
      tags: body.tags ?? [],
      folderId: body.folderId ?? null,
      objects: body.objects ?? [],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    }
    notes = [note, ...notes]
    return HttpResponse.json(note, { status: 201 })
  }),

  http.patch('/api/notes/:slug', async ({ params, request }) => {
    const body = await request.json() as Partial<Note>
    const idx = notes.findIndex(n => n.slug === params.slug)
    if (idx === -1) return HttpResponse.json({ error: 'Not found' }, { status: 404 })
    notes[idx] = { ...notes[idx], ...body, updatedAt: new Date().toISOString() }
    return HttpResponse.json(notes[idx])
  }),
]
