import type { Note } from '../../types'

export const noteFixtures: Note[] = [
  {
    id: '1',
    slug: 'react-performance-tips',
    type: 'simple',
    title: 'React Performance Tips',
    cover: null,
    tags: [
      { id: 't1', name: 'react' },
      { id: 't2', name: 'performance' },
    ],
    folderId: 'f1',
    objects: [
      {
        id: 'o1',
        type: 'text',
        content: 'Use React.memo for expensive components that render often with same props.',
        createdAt: '2026-04-01T10:00:00Z',
      },
    ],
    createdAt: '2026-04-01T10:00:00Z',
    updatedAt: '2026-04-01T10:00:00Z',
  },
  {
    id: '2',
    slug: 'design-resources',
    type: 'collection',
    title: 'Design Resources',
    cover: null,
    tags: [{ id: 't3', name: 'design' }],
    folderId: 'f2',
    objects: [
      {
        id: 'o2',
        type: 'link',
        content: 'https://figma.com',
        createdAt: '2026-04-02T10:00:00Z',
      },
      {
        id: 'o3',
        type: 'link',
        content: 'https://dribbble.com',
        createdAt: '2026-04-02T10:01:00Z',
      },
    ],
    createdAt: '2026-04-02T10:00:00Z',
    updatedAt: '2026-04-02T10:01:00Z',
  },
  {
    id: '3',
    slug: 'system-architecture',
    type: 'composite',
    title: 'System Architecture',
    cover: null,
    tags: [{ id: 't4', name: 'architecture' }],
    folderId: 'f1',
    objects: [
      {
        id: 'o4',
        type: 'document',
        content: 'architecture.pdf',
        createdAt: '2026-04-03T10:00:00Z',
      },
      {
        id: 'o5',
        type: 'text',
        content: 'Main system overview document.',
        createdAt: '2026-04-03T10:01:00Z',
      },
    ],
    createdAt: '2026-04-03T10:00:00Z',
    updatedAt: '2026-04-03T10:01:00Z',
  },
]
