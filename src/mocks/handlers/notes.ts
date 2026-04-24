import { http, HttpResponse } from 'msw'
import { noteFixtures } from '../fixtures/notes'
import type { Note } from '../../types'

let notes = [...noteFixtures]

export const noteHandlers = [
  http.get('/api/notes', ({ request }) => {
    const url = new URL(request.url)
    const search = url.searchParams.get('search')?.toLowerCase()
    const tags = url.searchParams.get('tags')?.split(',').filter(Boolean)
    const folders = url.searchParams.get('folders')?.split(',').filter(Boolean)

    let result = notes
    if (search) {
      result = result.filter(n => n.title.toLowerCase().includes(search))
    }
    if (tags?.length) {
      result = result.filter(n => n.tags.some(t => tags.includes(t.name)))
    }
    if (folders?.length) {
      result = result.filter(n => n.folderId !== null && folders.includes(n.folderId))
    }
    return HttpResponse.json(result)
  }),

  http.get('/api/notes/:slug', ({ params }) => {
    const note = notes.find(n => n.slug === params.slug)
    if (!note) return HttpResponse.json({ error: 'Not found' }, { status: 404 })
    return HttpResponse.json(note)
  }),

  // Добавление файлов в существующую заметку (сценарий C — долгий hover)
  http.post('/api/notes/add-files', async ({ request }) => {
    const formData = await request.formData()
    const noteId = formData.get('noteId') as string
    const files  = formData.getAll('files') as File[]

    const idx = notes.findIndex(n => n.id === noteId)
    if (idx === -1) return HttpResponse.json({ error: 'Not found' }, { status: 404 })

    const STOCK_IMAGES = [
      'https://images.unsplash.com/photo-1519125323398-675f0ddb6308?w=480&h=640&fit=crop',
      'https://images.unsplash.com/photo-1476514525535-07fb3b4ae5f1?w=480&h=640&fit=crop',
      'https://images.unsplash.com/photo-1500534314209-a25ddb2bd429?w=480&h=640&fit=crop',
    ]
    const STOCK_DOC_COVERS = [
      'https://images.unsplash.com/photo-1586281380349-632531db7ed4?w=480&h=640&fit=crop',
      'https://images.unsplash.com/photo-1554224155-6726b3ff858f?w=480&h=640&fit=crop',
    ]

    let imgIdx = 0; let docIdx = 0
    const newObjects: Note['objects'] = files.map((file, i) => {
      const isImage = file.type.startsWith('image/')
      return isImage
        ? { id: `add-${Date.now()}-${i}`, type: 'image', content: STOCK_IMAGES[imgIdx++ % STOCK_IMAGES.length], createdAt: new Date().toISOString() }
        : { id: `add-${Date.now()}-${i}`, type: 'document', content: file.name, cover: STOCK_DOC_COVERS[docIdx++ % STOCK_DOC_COVERS.length], createdAt: new Date().toISOString() }
    })

    const updated: Note = {
      ...notes[idx],
      type: 'collection',
      objects: [...notes[idx].objects, ...newObjects],
      updatedAt: new Date().toISOString(),
    }
    notes[idx] = updated
    return HttpResponse.json(updated)
  }),

  // Загрузка файлов → новая заметка
  http.post('/api/notes/upload', async ({ request }) => {
    const formData = await request.formData()
    const files = formData.getAll('files') as File[]

    const STOCK_IMAGES = [
      'https://images.unsplash.com/photo-1519125323398-675f0ddb6308?w=480&h=640&fit=crop',
      'https://images.unsplash.com/photo-1476514525535-07fb3b4ae5f1?w=480&h=640&fit=crop',
      'https://images.unsplash.com/photo-1500534314209-a25ddb2bd429?w=480&h=640&fit=crop',
      'https://images.unsplash.com/photo-1531746020798-e6953c6e8e04?w=480&h=640&fit=crop',
      'https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=480&h=640&fit=crop',
    ]

    // Стоковые скриншоты документов (имитация PDF/DOC превью)
    const STOCK_DOC_COVERS = [
      'https://images.unsplash.com/photo-1586281380349-632531db7ed4?w=480&h=640&fit=crop',
      'https://images.unsplash.com/photo-1554224155-6726b3ff858f?w=480&h=640&fit=crop',
      'https://images.unsplash.com/photo-1568667256549-094345857949?w=480&h=640&fit=crop',
    ]

    let imgIdx = 0
    let docIdx = 0

    const objects: Note['objects'] = files.map((file, i) => {
      const isImage = file.type.startsWith('image/')
      if (isImage) {
        return {
          id: `upload-${Date.now()}-${i}`,
          type: 'image',
          content: STOCK_IMAGES[imgIdx++ % STOCK_IMAGES.length],
          createdAt: new Date().toISOString(),
        } satisfies Note['objects'][number]
      } else {
        return {
          id: `upload-${Date.now()}-${i}`,
          type: 'document',
          content: file.name,
          cover: STOCK_DOC_COVERS[docIdx++ % STOCK_DOC_COVERS.length],
          createdAt: new Date().toISOString(),
        } satisfies Note['objects'][number]
      }
    })

    const firstImage = objects.find(o => o.type === 'image')
    const note: Note = {
      id: String(Date.now()),
      slug: `upload-${Date.now()}`,
      type: files.length > 1 ? 'collection' : 'simple',
      title: files[0]?.name.replace(/\.[^.]+$/, '') ?? 'Новая заметка',
      cover: firstImage?.content ?? null,
      tags: [],
      folderId: null,
      objects,
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

  // Создание заметки (текст / объекты) — ПОСЛЕ специфичных /upload /add-files /merge
  http.post('/api/notes', async ({ request }) => {
    const body = await request.json() as Partial<Note>

    const id = String(Date.now())
    const note: Note = {
      id,
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

  http.post('/api/notes/merge', async ({ request }) => {
    const { sourceId, targetId } = await request.json() as { sourceId: string; targetId: string }
    const source = notes.find(n => n.id === sourceId)
    const target = notes.find(n => n.id === targetId)
    if (!source || !target) return HttpResponse.json({ error: 'Not found' }, { status: 404 })

    let updated: Note

    if (target.type === 'collection') {
      // X становится элементом коллекции Y
      updated = {
        ...target,
        objects: [...target.objects, ...source.objects],
        updatedAt: new Date().toISOString(),
      }
      notes = notes.map(n => n.id === target.id ? updated : n).filter(n => n.id !== source.id)
    } else {
      // Создаём новую коллекцию [X, Y] на месте Y — сохраняем id/slug цели,
      // чтобы карточка осталась в той же колонке грида
      const textObj = source.objects.find(o => o.type === 'text') ?? target.objects.find(o => o.type === 'text')
      updated = {
        ...target,
        type: 'collection',
        title: textObj?.content.slice(0, 40) ?? 'Новая коллекция',
        tags: [...target.tags, ...source.tags.filter(st => !target.tags.some(tt => tt.id === st.id))],
        objects: [...target.objects, ...source.objects],
        updatedAt: new Date().toISOString(),
      }
      notes = notes.map(n => n.id === target.id ? updated : n).filter(n => n.id !== source.id)
    }

    return HttpResponse.json({ updated, removedId: source.id })
  }),
]
