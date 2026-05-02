# Frontend Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Создать работающий фронтенд-скаффолд для Seyvix с роутингом, слоем данных и MSW-моками.

**Architecture:** SPA на React 19 + Vite с client-side роутингом через React Router v7 (Library mode). Серверный стейт через TanStack Query. MSW перехватывает API-запросы в dev-режиме через Service Worker, в продакшн не попадает.

**Tech Stack:** React 19, Vite 6, TypeScript 5, React Router v7, TanStack Query v5, MSW v2, Framer Motion, pragmatic-drag-and-drop, React Flow (@xyflow/react), CSS Modules

---

### Task 1: Конфигурационные файлы проекта

**Files:**
- Create: `.gitignore`
- Create: `package.json`
- Create: `vite.config.ts`
- Create: `tsconfig.json`
- Create: `tsconfig.app.json`
- Create: `tsconfig.node.json`
- Create: `index.html`

- [ ] **Step 1: Создать `package.json`**

```json
{
  "name": "seyvix-web",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "@atlaskit/pragmatic-drag-and-drop": "^1.4.0",
    "@tanstack/react-query": "^5.74.4",
    "@xyflow/react": "^12.6.0",
    "framer-motion": "^12.7.3",
    "react": "^19.1.0",
    "react-dom": "^19.1.0",
    "react-router-dom": "^7.5.1"
  },
  "devDependencies": {
    "@types/react": "^19.1.2",
    "@types/react-dom": "^19.1.2",
    "@vitejs/plugin-react": "^4.4.1",
    "msw": "^2.7.5",
    "typescript": "^5.8.3",
    "vite": "^6.3.3"
  }
}
```

- [ ] **Step 2: Создать `vite.config.ts`**

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
})
```

- [ ] **Step 3: Создать `tsconfig.json`**

```json
{
  "files": [],
  "references": [
    { "path": "./tsconfig.app.json" },
    { "path": "./tsconfig.node.json" }
  ]
}
```

- [ ] **Step 4: Создать `tsconfig.app.json`**

```json
{
  "compilerOptions": {
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.app.tsbuildinfo",
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true
  },
  "include": ["src"]
}
```

- [ ] **Step 5: Создать `tsconfig.node.json`**

```json
{
  "compilerOptions": {
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.node.tsbuildinfo",
    "target": "ES2022",
    "lib": ["ES2023"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 6: Создать `.gitignore`**

```
node_modules
dist
.DS_Store
*.local
```

- [ ] **Step 7: Создать `index.html`**

```html
<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Seyvix</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 8: Установить зависимости**

```bash
npm install
```

Ожидаемый результат: появится `node_modules/`, файл `package-lock.json`.

- [ ] **Step 9: Commit**

```bash
git add .gitignore package.json vite.config.ts tsconfig.json tsconfig.app.json tsconfig.node.json index.html package-lock.json
git commit -m "chore: init vite project config"
```

---

### Task 2: Глобальные стили

**Files:**
- Create: `src/styles/reset.css`
- Create: `src/styles/variables.css`

- [ ] **Step 1: Создать `src/styles/reset.css`**

```css
*, *::before, *::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

html {
  -webkit-text-size-adjust: 100%;
}

body {
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}

img, picture, video, canvas, svg {
  display: block;
  max-width: 100%;
}

input, button, textarea, select {
  font: inherit;
}

p, h1, h2, h3, h4, h5, h6 {
  overflow-wrap: break-word;
}

#root {
  isolation: isolate;
}
```

- [ ] **Step 2: Создать `src/styles/variables.css`**

```css
:root {
  /* Colors */
  --color-bg: #0f0f0f;
  --color-surface: #1a1a1a;
  --color-surface-hover: #222222;
  --color-border: #2a2a2a;
  --color-text-primary: #f5f5f5;
  --color-text-secondary: #8a8a8a;
  --color-accent: #6366f1;
  --color-accent-hover: #4f46e5;
  --color-danger: #ef4444;

  /* Spacing */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;
  --space-10: 40px;
  --space-12: 48px;

  /* Typography */
  --font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  --font-size-xs: 11px;
  --font-size-sm: 13px;
  --font-size-base: 15px;
  --font-size-lg: 18px;
  --font-size-xl: 22px;
  --font-size-2xl: 28px;
  --font-weight-normal: 400;
  --font-weight-medium: 500;
  --font-weight-semibold: 600;

  /* Motion */
  --duration-fast: 120ms;
  --duration-normal: 220ms;
  --duration-slow: 350ms;
  --ease-default: cubic-bezier(0.4, 0, 0.2, 1);
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);

  /* Border Radius */
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 16px;
  --radius-xl: 24px;

  /* Shadows */
  --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.3);
  --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.4);
  --shadow-lg: 0 8px 32px rgba(0, 0, 0, 0.5);
}
```

- [ ] **Step 3: Commit**

```bash
git add src/styles/
git commit -m "feat: add global CSS reset and design tokens"
```

---

### Task 3: TypeScript типы

**Files:**
- Create: `src/types/index.ts`

- [ ] **Step 1: Создать `src/types/index.ts`**

```ts
export type NoteType = 'simple' | 'composite' | 'collection'

export type NoteObjectType = 'text' | 'image' | 'link' | 'document'

export interface Tag {
  id: string
  name: string
}

export interface Folder {
  id: string
  slug: string
  name: string
  parentId: string | null
  children: Folder[]
}

export interface NoteObject {
  id: string
  type: NoteObjectType
  content: string
  createdAt: string
}

export interface Note {
  id: string
  slug: string
  type: NoteType
  title: string
  cover: string | null
  tags: Tag[]
  folderId: string | null
  objects: NoteObject[]
  createdAt: string
  updatedAt: string
}

export interface NotesParams {
  search?: string
  tags?: string[]
  folders?: string[]
}
```

- [ ] **Step 2: Commit**

```bash
git add src/types/
git commit -m "feat: add TypeScript domain types"
```

---

### Task 4: API слой

**Files:**
- Create: `src/api/notes.ts`
- Create: `src/api/folders.ts`

- [ ] **Step 1: Создать `src/api/notes.ts`**

```ts
import type { Note, NotesParams } from '../types'

export async function fetchNotes(params: NotesParams = {}): Promise<Note[]> {
  const url = new URL('/api/notes', window.location.origin)
  if (params.search) url.searchParams.set('search', params.search)
  if (params.tags?.length) url.searchParams.set('tags', params.tags.join(','))
  if (params.folders?.length) url.searchParams.set('folders', params.folders.join(','))

  const res = await fetch(url)
  if (!res.ok) throw new Error('Failed to fetch notes')
  return res.json() as Promise<Note[]>
}

export async function fetchNote(slug: string): Promise<Note> {
  const res = await fetch(`/api/notes/${slug}`)
  if (!res.ok) throw new Error('Failed to fetch note')
  return res.json() as Promise<Note>
}

export async function createNote(data: Partial<Note>): Promise<Note> {
  const res = await fetch('/api/notes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to create note')
  return res.json() as Promise<Note>
}

export async function updateNote(slug: string, data: Partial<Note>): Promise<Note> {
  const res = await fetch(`/api/notes/${slug}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to update note')
  return res.json() as Promise<Note>
}
```

- [ ] **Step 2: Создать `src/api/folders.ts`**

```ts
import type { Folder } from '../types'

export async function fetchFolders(): Promise<Folder[]> {
  const res = await fetch('/api/folders')
  if (!res.ok) throw new Error('Failed to fetch folders')
  return res.json() as Promise<Folder[]>
}

export async function fetchFolder(slug: string): Promise<Folder> {
  const res = await fetch(`/api/folders/${slug}`)
  if (!res.ok) throw new Error('Failed to fetch folder')
  return res.json() as Promise<Folder>
}
```

- [ ] **Step 3: Commit**

```bash
git add src/api/
git commit -m "feat: add API layer functions"
```

---

### Task 5: Хуки TanStack Query

**Files:**
- Create: `src/hooks/useNotes.ts`
- Create: `src/hooks/useNote.ts`
- Create: `src/hooks/useFolders.ts`
- Create: `src/hooks/useFolder.ts`

- [ ] **Step 1: Создать `src/hooks/useNotes.ts`**

```ts
import { useQuery } from '@tanstack/react-query'
import { fetchNotes } from '../api/notes'
import type { NotesParams } from '../types'

export function useNotes(params: NotesParams = {}) {
  return useQuery({
    queryKey: ['notes', params],
    queryFn: () => fetchNotes(params),
  })
}
```

- [ ] **Step 2: Создать `src/hooks/useNote.ts`**

```ts
import { useQuery } from '@tanstack/react-query'
import { fetchNote } from '../api/notes'

export function useNote(slug: string) {
  return useQuery({
    queryKey: ['note', slug],
    queryFn: () => fetchNote(slug),
    enabled: !!slug,
  })
}
```

- [ ] **Step 3: Создать `src/hooks/useFolders.ts`**

```ts
import { useQuery } from '@tanstack/react-query'
import { fetchFolders } from '../api/folders'

export function useFolders() {
  return useQuery({
    queryKey: ['folders'],
    queryFn: fetchFolders,
  })
}
```

- [ ] **Step 4: Создать `src/hooks/useFolder.ts`**

```ts
import { useQuery } from '@tanstack/react-query'
import { fetchFolder } from '../api/folders'

export function useFolder(slug: string) {
  return useQuery({
    queryKey: ['folder', slug],
    queryFn: () => fetchFolder(slug),
    enabled: !!slug,
  })
}
```

- [ ] **Step 5: Commit**

```bash
git add src/hooks/
git commit -m "feat: add TanStack Query hooks"
```

---

### Task 6: MSW фикстуры и хэндлеры

**Files:**
- Create: `src/mocks/fixtures/notes.ts`
- Create: `src/mocks/fixtures/folders.ts`
- Create: `src/mocks/handlers/notes.ts`
- Create: `src/mocks/handlers/folders.ts`
- Create: `src/mocks/browser.ts`

- [ ] **Step 1: Создать `src/mocks/fixtures/notes.ts`**

```ts
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
```

- [ ] **Step 2: Создать `src/mocks/fixtures/folders.ts`**

```ts
import type { Folder } from '../../types'

export const folderFixtures: Folder[] = [
  {
    id: 'f1',
    slug: 'engineering',
    name: 'Engineering',
    parentId: null,
    children: [
      {
        id: 'f3',
        slug: 'engineering-frontend',
        name: 'Frontend',
        parentId: 'f1',
        children: [],
      },
      {
        id: 'f4',
        slug: 'engineering-backend',
        name: 'Backend',
        parentId: 'f1',
        children: [],
      },
    ],
  },
  {
    id: 'f2',
    slug: 'design',
    name: 'Design',
    parentId: null,
    children: [],
  },
]
```

- [ ] **Step 3: Создать `src/mocks/handlers/notes.ts`**

```ts
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
```

- [ ] **Step 4: Создать `src/mocks/handlers/folders.ts`**

```ts
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
```

- [ ] **Step 5: Создать `src/mocks/browser.ts`**

```ts
import { setupWorker } from 'msw/browser'
import { noteHandlers } from './handlers/notes'
import { folderHandlers } from './handlers/folders'

export const worker = setupWorker(...noteHandlers, ...folderHandlers)
```

- [ ] **Step 6: Commit**

```bash
git add src/mocks/
git commit -m "feat: add MSW mocks with fixtures and handlers"
```

---

### Task 7: Страницы-заглушки

**Files:**
- Create: `src/pages/NotesPage.tsx`
- Create: `src/pages/NotePage.tsx`
- Create: `src/pages/NoteEditPage.tsx`
- Create: `src/pages/FoldersPage.tsx`
- Create: `src/pages/FolderPage.tsx`

- [ ] **Step 1: Создать `src/pages/NotesPage.tsx`**

```tsx
export default function NotesPage() {
  return <div>Notes Dashboard</div>
}
```

- [ ] **Step 2: Создать `src/pages/NotePage.tsx`**

```tsx
import { useParams } from 'react-router-dom'

export default function NotePage() {
  const { noteSlug } = useParams<{ noteSlug: string }>()
  return <div>Note: {noteSlug}</div>
}
```

- [ ] **Step 3: Создать `src/pages/NoteEditPage.tsx`**

```tsx
import { useParams } from 'react-router-dom'

export default function NoteEditPage() {
  const { noteSlug } = useParams<{ noteSlug: string }>()
  return <div>Edit Note: {noteSlug}</div>
}
```

- [ ] **Step 4: Создать `src/pages/FoldersPage.tsx`**

```tsx
export default function FoldersPage() {
  return <div>Folders MindMap</div>
}
```

- [ ] **Step 5: Создать `src/pages/FolderPage.tsx`**

```tsx
import { useParams } from 'react-router-dom'

export default function FolderPage() {
  const { folderSlug } = useParams<{ folderSlug: string }>()
  return <div>Folder: {folderSlug}</div>
}
```

- [ ] **Step 6: Commit**

```bash
git add src/pages/
git commit -m "feat: add page stubs for all routes"
```

---

### Task 8: App.tsx — роутер и QueryClientProvider

**Files:**
- Create: `src/App.tsx`

- [ ] **Step 1: Создать `src/App.tsx`**

```tsx
import { createBrowserRouter, RouterProvider, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5,
      retry: 1,
    },
  },
})

const router = createBrowserRouter([
  {
    path: '/',
    element: <Navigate to="/notes" replace />,
  },
  {
    path: '/notes',
    lazy: async () => ({ Component: (await import('./pages/NotesPage')).default }),
  },
  {
    path: '/notes/:noteSlug',
    lazy: async () => ({ Component: (await import('./pages/NotePage')).default }),
  },
  {
    path: '/notes/:noteSlug/edit',
    lazy: async () => ({ Component: (await import('./pages/NoteEditPage')).default }),
  },
  {
    path: '/folders',
    lazy: async () => ({ Component: (await import('./pages/FoldersPage')).default }),
  },
  {
    path: '/folders/:folderSlug',
    lazy: async () => ({ Component: (await import('./pages/FolderPage')).default }),
  },
])

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add src/App.tsx
git commit -m "feat: add router and QueryClientProvider"
```

---

### Task 9: main.tsx — точка входа с MSW

**Files:**
- Create: `src/main.tsx`

- [ ] **Step 1: Создать `src/main.tsx`**

```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/reset.css'
import './styles/variables.css'
import App from './App'

async function prepare(): Promise<void> {
  if (import.meta.env.DEV) {
    const { worker } = await import('./mocks/browser')
    await worker.start({ onUnhandledRequest: 'bypass' })
  }
}

prepare().then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>
  )
})
```

- [ ] **Step 2: Commit**

```bash
git add src/main.tsx
git commit -m "feat: add entry point with MSW initialization"
```

---

### Task 10: MSW Service Worker и финальная проверка

**Files:**
- Create: `public/mockServiceWorker.js` (генерируется командой)

- [ ] **Step 1: Инициализировать MSW Service Worker**

```bash
npx msw init public/
```

Ожидаемый результат: создан файл `public/mockServiceWorker.js`.

- [ ] **Step 2: Добавить `public/` в git (кроме `mockServiceWorker.js`)**

MSW рекомендует коммитить `mockServiceWorker.js` — это стандартный служебный файл, не генерируемый при сборке.

```bash
git add public/mockServiceWorker.js
git commit -m "chore: add MSW service worker"
```

- [ ] **Step 3: Запустить dev-сервер**

```bash
npm run dev
```

Ожидаемый результат в браузере:
1. Открыть `http://localhost:5173` → редирект на `/notes` → отображается `Notes Dashboard`
2. В консоли браузера: `[MSW] Mocking enabled.`
3. Перейти на `http://localhost:5173/folders` → отображается `Folders MindMap`
4. Перейти на `http://localhost:5173/notes/react-performance-tips` → `Note: react-performance-tips`

- [ ] **Step 4: Проверить TypeScript**

```bash
npx tsc --noEmit
```

Ожидаемый результат: нет ошибок.

- [ ] **Step 5: Commit финального состояния**

```bash
git add -A
git commit -m "chore: verify setup complete"
```
