import type { Note } from '../../types'

// Порядок подобран так чтобы при распределении (i+1) % 4
// каждая из 4 колонок содержала все три типа заметок.
//
// Слот 0 в col-0 = AddNoteCard
// note[i] → колонка (i+1) % 4
// col-0: note 3,7,11   col-1: note 0,4,8,12   col-2: note 1,5,9   col-3: note 2,6,10

export const noteFixtures: Note[] = [
  // col-1 — simple (текст)
  {
    id: '1',
    slug: 'react-performance-tips',
    type: 'simple',
    title: 'React Performance Tips',
    cover: null,
    tags: [{ id: 't1', name: 'react' }, { id: 't2', name: 'performance' }],
    folderId: 'f1',
    objects: [
      { id: 'o1', type: 'text', content: 'Use React.memo for expensive components that render often with same props. Avoid anonymous functions in JSX.', createdAt: '2026-04-01T10:00:00Z' },
    ],
    createdAt: '2026-04-01T10:00:00Z',
    updatedAt: '2026-04-01T10:00:00Z',
  },

  // col-2 — collection
  {
    id: '2',
    slug: 'design-resources',
    type: 'collection',
    title: 'Design Resources',
    cover: null,
    tags: [{ id: 't3', name: 'design' }, { id: 't4', name: 'links' }],
    folderId: 'f2',
    objects: [
      { id: 'o2a', type: 'image', content: 'https://images.unsplash.com/photo-1561070791-2526d30994b5?w=400&h=300&fit=crop', createdAt: '2026-04-02T10:00:00Z' },
      { id: 'o2b', type: 'image', content: 'https://images.unsplash.com/photo-1626785774625-0b1c2c4eab67?w=400&h=300&fit=crop', createdAt: '2026-04-02T10:01:00Z' },
      { id: 'o2c', type: 'image', content: 'https://images.unsplash.com/photo-1545235617-9465d2a55698?w=400&h=300&fit=crop', createdAt: '2026-04-02T10:02:00Z' },
      { id: 'o2d', type: 'image', content: 'https://images.unsplash.com/photo-1581291518857-4e27b48ff24e?w=400&h=300&fit=crop', createdAt: '2026-04-02T10:03:00Z' },
      { id: 'o2e', type: 'image', content: 'https://images.unsplash.com/photo-1558655146-9f40138edfeb?w=400&h=300&fit=crop', createdAt: '2026-04-02T10:04:00Z' },
      { id: 'o2f', type: 'link',  content: 'https://figma.com',    createdAt: '2026-04-02T10:05:00Z' },
      { id: 'o2g', type: 'link',  content: 'https://dribbble.com', createdAt: '2026-04-02T10:06:00Z' },
    ],
    createdAt: '2026-04-02T10:00:00Z',
    updatedAt: '2026-04-02T10:06:00Z',
  },

  // col-3 — composite (текст + документ со скриншотом)
  {
    id: '3',
    slug: 'system-architecture',
    type: 'composite',
    title: 'System Architecture',
    cover: null,
    tags: [{ id: 't5', name: 'arch' }],
    folderId: 'f1',
    objects: [
      { id: 'o3a', type: 'text', content: 'Микросервисы, очереди событий, API gateway. Каждый сервис — одна зона ответственности.', createdAt: '2026-04-03T10:00:00Z' },
      { id: 'o3b', type: 'document', content: 'architecture.pdf', cover: 'https://images.unsplash.com/photo-1618044733300-9472054094ee?w=600&h=800&fit=crop', createdAt: '2026-04-03T10:01:00Z' },
    ],
    createdAt: '2026-04-03T10:00:00Z',
    updatedAt: '2026-04-03T10:01:00Z',
  },

  // col-0 — simple (картинка 1:1)
  {
    id: '4',
    slug: 'mountain-photo',
    type: 'simple',
    title: 'Горный пейзаж',
    cover: null,
    tags: [{ id: 't6', name: 'photo' }],
    folderId: null,
    objects: [
      { id: 'o4', type: 'image', content: 'https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=600&h=600&fit=crop', createdAt: '2026-04-04T10:00:00Z' },
    ],
    createdAt: '2026-04-04T10:00:00Z',
    updatedAt: '2026-04-04T10:00:00Z',
  },

  // col-1 — collection
  {
    id: '5',
    slug: 'book-notes',
    type: 'collection',
    title: 'Book Notes 2026',
    cover: null,
    tags: [{ id: 't7', name: 'books' }, { id: 't8', name: 'learning' }],
    folderId: null,
    objects: [
      { id: 'o5a', type: 'image', content: 'https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?w=400&h=300&fit=crop', createdAt: '2026-04-05T10:00:00Z' },
      { id: 'o5b', type: 'image', content: 'https://images.unsplash.com/photo-1512820790803-83ca734da794?w=400&h=300&fit=crop', createdAt: '2026-04-05T10:01:00Z' },
      { id: 'o5c', type: 'image', content: 'https://images.unsplash.com/photo-1481627834876-b7833e8f5570?w=400&h=300&fit=crop', createdAt: '2026-04-05T10:02:00Z' },
      { id: 'o5d', type: 'image', content: 'https://images.unsplash.com/photo-1495446815901-a7297e633e8d?w=400&h=300&fit=crop', createdAt: '2026-04-05T10:03:00Z' },
      { id: 'o5e', type: 'image', content: 'https://images.unsplash.com/photo-1524995997946-a1c2e315a42f?w=400&h=300&fit=crop', createdAt: '2026-04-05T10:04:00Z' },
      { id: 'o5f', type: 'image', content: 'https://images.unsplash.com/photo-1506880018603-83d5b814b5a6?w=400&h=300&fit=crop', createdAt: '2026-04-05T10:05:00Z' },
      { id: 'o5g', type: 'text',  content: 'Atomic Habits',            createdAt: '2026-04-05T10:06:00Z' },
      { id: 'o5h', type: 'text',  content: 'Deep Work',                createdAt: '2026-04-05T10:07:00Z' },
      { id: 'o5i', type: 'text',  content: 'The Pragmatic Programmer', createdAt: '2026-04-05T10:08:00Z' },
      { id: 'o5j', type: 'text',  content: 'SICP',                     createdAt: '2026-04-05T10:09:00Z' },
    ],
    createdAt: '2026-04-05T10:00:00Z',
    updatedAt: '2026-04-05T10:09:00Z',
  },

  // col-2 — composite (текст + ссылка + картинка)
  {
    id: '6',
    slug: 'framer-motion-research',
    type: 'composite',
    title: 'Framer Motion Research',
    cover: null,
    tags: [{ id: 't9', name: 'animation' }, { id: 't10', name: 'react' }],
    folderId: 'f1',
    objects: [
      { id: 'o6a', type: 'text',  content: 'layoutId связывает элементы между рендерами для shared-element transitions.', createdAt: '2026-04-06T10:00:00Z' },
      { id: 'o6b', type: 'link',  content: 'https://motion.dev', createdAt: '2026-04-06T10:01:00Z' },
      { id: 'o6c', type: 'image', content: 'https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=400&h=300&fit=crop', createdAt: '2026-04-06T10:02:00Z' },
    ],
    createdAt: '2026-04-06T10:00:00Z',
    updatedAt: '2026-04-06T10:02:00Z',
  },

  // col-3 — simple (текст)
  {
    id: '7',
    slug: 'typescript-patterns',
    type: 'simple',
    title: 'TypeScript Patterns',
    cover: null,
    tags: [{ id: 't11', name: 'typescript' }],
    folderId: null,
    objects: [
      { id: 'o7', type: 'text', content: 'Generic constraints и conditional types позволяют строить гибкие типы без потери безопасности. Используй infer для извлечения типов.', createdAt: '2026-04-07T10:00:00Z' },
    ],
    createdAt: '2026-04-07T10:00:00Z',
    updatedAt: '2026-04-07T10:00:00Z',
  },

  // col-0 — collection
  {
    id: '8',
    slug: 'dev-tools',
    type: 'collection',
    title: 'Dev Tools',
    cover: null,
    tags: [{ id: 't12', name: 'tools' }, { id: 't13', name: 'productivity' }],
    folderId: 'f2',
    objects: [
      { id: 'o8a', type: 'image', content: 'https://images.unsplash.com/photo-1555066931-4365d14bab8c?w=400&h=300&fit=crop', createdAt: '2026-04-08T10:00:00Z' },
      { id: 'o8b', type: 'image', content: 'https://images.unsplash.com/photo-1629654297299-c8506221ca97?w=400&h=300&fit=crop', createdAt: '2026-04-08T10:01:00Z' },
      { id: 'o8c', type: 'image', content: 'https://images.unsplash.com/photo-1587620962725-abab7fe55159?w=400&h=300&fit=crop', createdAt: '2026-04-08T10:02:00Z' },
      { id: 'o8d', type: 'image', content: 'https://images.unsplash.com/photo-1498050108023-c5249f4df085?w=400&h=300&fit=crop', createdAt: '2026-04-08T10:03:00Z' },
      { id: 'o8e', type: 'link',  content: 'https://linear.app',  createdAt: '2026-04-08T10:04:00Z' },
      { id: 'o8f', type: 'link',  content: 'https://warp.dev',    createdAt: '2026-04-08T10:05:00Z' },
      { id: 'o8g', type: 'link',  content: 'https://raycast.com', createdAt: '2026-04-08T10:06:00Z' },
    ],
    createdAt: '2026-04-08T10:00:00Z',
    updatedAt: '2026-04-08T10:06:00Z',
  },

  // col-1 — composite (4 объекта, документ со скриншотом)
  {
    id: '9',
    slug: 'postgres-research',
    type: 'composite',
    title: 'PostgreSQL Research',
    cover: null,
    tags: [{ id: 't14', name: 'db' }, { id: 't15', name: 'backend' }],
    folderId: 'f1',
    objects: [
      { id: 'o9a', type: 'text',     content: 'EXPLAIN ANALYZE покажет где запрос теряет время. Partial indexes ускоряют фильтрацию.', createdAt: '2026-04-09T10:00:00Z' },
      { id: 'o9b', type: 'document', content: 'postgres-notes.pdf', cover: 'https://images.unsplash.com/photo-1558494949-ef010cbdcc31?w=600&h=800&fit=crop', createdAt: '2026-04-09T10:01:00Z' },
      { id: 'o9c', type: 'image',    content: 'https://images.unsplash.com/photo-1544383835-bda2bc66a55d?w=400&h=300&fit=crop', createdAt: '2026-04-09T10:02:00Z' },
      { id: 'o9d', type: 'link',     content: 'https://explain.dalibo.com', createdAt: '2026-04-09T10:03:00Z' },
    ],
    createdAt: '2026-04-09T10:00:00Z',
    updatedAt: '2026-04-09T10:03:00Z',
  },

  // col-2 — simple (широкая картинка 16:9)
  {
    id: '10',
    slug: 'landscape-ref',
    type: 'simple',
    title: 'Landscape Reference',
    cover: null,
    tags: [{ id: 't16', name: 'photo' }, { id: 't17', name: 'ref' }],
    folderId: null,
    objects: [
      { id: 'o10', type: 'image', content: 'https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?w=800&h=450&fit=crop', createdAt: '2026-04-10T10:00:00Z' },
    ],
    createdAt: '2026-04-10T10:00:00Z',
    updatedAt: '2026-04-10T10:00:00Z',
  },

  // col-3 — collection
  {
    id: '11',
    slug: 'css-references',
    type: 'collection',
    title: 'CSS References',
    cover: null,
    tags: [{ id: 't18', name: 'css' }, { id: 't19', name: 'frontend' }],
    folderId: 'f2',
    objects: [
      { id: 'o11a', type: 'image', content: 'https://images.unsplash.com/photo-1507721999472-8ed4421c4af2?w=400&h=300&fit=crop', createdAt: '2026-04-11T10:00:00Z' },
      { id: 'o11b', type: 'image', content: 'https://images.unsplash.com/photo-1542831371-29b0f74f9713?w=400&h=300&fit=crop', createdAt: '2026-04-11T10:01:00Z' },
      { id: 'o11c', type: 'image', content: 'https://images.unsplash.com/photo-1517694712202-14dd9538aa97?w=400&h=300&fit=crop', createdAt: '2026-04-11T10:02:00Z' },
      { id: 'o11d', type: 'link',  content: 'https://css-tricks.com', createdAt: '2026-04-11T10:03:00Z' },
      { id: 'o11e', type: 'link',  content: 'https://web.dev',        createdAt: '2026-04-11T10:04:00Z' },
    ],
    createdAt: '2026-04-11T10:00:00Z',
    updatedAt: '2026-04-11T10:04:00Z',
  },

  // col-0 — composite (текст + документ со скриншотом)
  {
    id: '12',
    slug: 'vim-research',
    type: 'composite',
    title: 'Vim Research',
    cover: null,
    tags: [{ id: 't20', name: 'tools' }, { id: 't21', name: 'editor' }],
    folderId: null,
    objects: [
      { id: 'o12a', type: 'text',     content: 'ci" меняет содержимое внутри кавычек. f<char> прыгает к символу на строке.', createdAt: '2026-04-12T10:00:00Z' },
      { id: 'o12b', type: 'document', content: 'vim-cheatsheet.pdf', cover: 'https://images.unsplash.com/photo-1629654297299-c8506221ca97?w=600&h=800&fit=crop', createdAt: '2026-04-12T10:01:00Z' },
    ],
    createdAt: '2026-04-12T10:00:00Z',
    updatedAt: '2026-04-12T10:01:00Z',
  },

  // col-1 — simple (вертикальная картинка)
  {
    id: '13',
    slug: 'portrait-ref',
    type: 'simple',
    title: 'Portrait Reference',
    cover: null,
    tags: [{ id: 't22', name: 'photo' }, { id: 't23', name: 'ref' }],
    folderId: null,
    objects: [
      { id: 'o13', type: 'image', content: 'https://images.unsplash.com/photo-1531746020798-e6953c6e8e04?w=480&h=600&fit=crop', createdAt: '2026-04-13T10:00:00Z' },
    ],
    createdAt: '2026-04-13T10:00:00Z',
    updatedAt: '2026-04-13T10:00:00Z',
  },

  // col-2 — collection (1 фото)
  {
    id: '14',
    slug: 'solo-shot',
    type: 'collection',
    title: 'Solo Shot',
    cover: null,
    tags: [{ id: 't24', name: 'photo' }],
    folderId: null,
    objects: [
      { id: 'o14a', type: 'image', content: 'https://images.unsplash.com/photo-1519125323398-675f0ddb6308?w=400&h=600&fit=crop', createdAt: '2026-04-14T10:00:00Z' },
    ],
    createdAt: '2026-04-14T10:00:00Z',
    updatedAt: '2026-04-14T10:00:00Z',
  },

  // col-3 — collection (2 фото)
  {
    id: '15',
    slug: 'duo-shots',
    type: 'collection',
    title: 'Duo Shots',
    cover: null,
    tags: [{ id: 't25', name: 'photo' }, { id: 't26', name: 'travel' }],
    folderId: null,
    objects: [
      { id: 'o15a', type: 'image', content: 'https://images.unsplash.com/photo-1500534314209-a25ddb2bd429?w=400&h=600&fit=crop', createdAt: '2026-04-15T10:00:00Z' },
      { id: 'o15b', type: 'image', content: 'https://images.unsplash.com/photo-1476514525535-07fb3b4ae5f1?w=400&h=600&fit=crop', createdAt: '2026-04-15T10:01:00Z' },
    ],
    createdAt: '2026-04-15T10:00:00Z',
    updatedAt: '2026-04-15T10:01:00Z',
  },
]
