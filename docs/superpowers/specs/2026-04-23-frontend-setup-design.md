# Frontend Setup Design — Seyvix Web

**Date:** 2026-04-23
**Project:** Seyvix — сервис умного хранения заметок

---

## 1. Стек

### Runtime зависимости

| Пакет | Назначение |
|---|---|
| `react`, `react-dom` (v19) | UI фреймворк |
| `react-router-dom` | Клиентский роутинг, lazy-loading роутов |
| `@tanstack/react-query` | Серверный стейт, кэш, оптимистичные обновления |
| `@atlaskit/pragmatic-drag-and-drop` | Drag & Drop механика + файлы из ОС (через `external/file` путь внутри пакета) |
| `framer-motion` | Layout-анимации, AnimatePresence |
| `@xyflow/react` | MindMap визуализация для /folders |

### Dev зависимости

| Пакет | Назначение |
|---|---|
| `vite`, `@vitejs/plugin-react` | Сборка и HMR |
| `typescript` | Типизация |
| `msw` | Моки API в dev-режиме (в прод не попадает) |

### Исключения и причины

- **Tailwind** — исключён намеренно, используем CSS Modules
- **UI-библиотеки** (MUI, Ant Design) — исключены, пишем компоненты вручную для контроля веса
- **Zustand / Redux** — не нужны, локальный стейт через `useState`/`useReducer`, серверный через TanStack Query
- **react-beautiful-dnd** — заархивирован, несовместим с React 19

---

## 2. Структура проекта

```
src/
├── api/              # Чистые async-функции запросов (fetchNotes, createNote...)
├── components/       # Переиспользуемые UI-компоненты (Card, LayerView, Skeleton...)
├── pages/            # Компоненты страниц
├── hooks/            # Кастомные хуки (useNotes, useNote, useSearch...)
├── mocks/            # MSW handlers + fixtures
│   ├── handlers/
│   │   ├── notes.ts
│   │   └── folders.ts
│   ├── fixtures/
│   │   ├── notes.ts
│   │   └── folders.ts
│   └── browser.ts
├── styles/           # Глобальные CSS
│   ├── reset.css
│   └── variables.css
├── types/            # TypeScript типы (Note, Folder, Tag...)
├── App.tsx           # Роутер + QueryClientProvider
└── main.tsx          # Точка входа + MSW инициализация
```

**Принципы:**
- `api/` не знает о React — только fetch-функции с типизированными ответами
- `hooks/` оборачивают `api/` через TanStack Query
- CSS Modules используют CSS Custom Properties из `variables.css`
- MSW инициализируется только при `import.meta.env.DEV`

---

## 3. Роутинг

```ts
const router = createBrowserRouter([
  { path: '/', element: <Navigate to="/notes" replace /> },
  { path: '/notes', lazy: () => import('./pages/NotesPage') },
  { path: '/notes/:noteSlug', lazy: () => import('./pages/NotePage') },
  { path: '/notes/:noteSlug/edit', lazy: () => import('./pages/NoteEditPage') },
  { path: '/folders', lazy: () => import('./pages/FoldersPage') },
  { path: '/folders/:folderSlug', lazy: () => import('./pages/FolderPage') },
])
```

**Ключевые решения:**
- `lazy:` — каждая страница в отдельном chunk. `@xyflow/react` (~200kb) загружается только при переходе на `/folders`
- CGI-параметры поиска (`?search=x&tags=y`) читаются через `useSearchParams()` внутри `NotesPage`
- Аутентификация отсутствует, все роуты публичны

---

## 4. Слой данных

### TanStack Query

```ts
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 минут
      retry: 1,
    },
  },
})
```

### Оптимистичные обновления

Паттерн для создания/изменения заметок:
1. `onMutate` — отменяем активные запросы, сохраняем предыдущее состояние, вставляем skeleton
2. `onError` — откатываем к предыдущему состоянию
3. `onSettled` — инвалидируем кэш, запрашиваем актуальные данные

### MSW

- `public/mockServiceWorker.js` — генерируется командой `npx msw init public/`
- Воркер регистрируется с автоматическим скоупом `/`, ручная конфигурация не нужна
- `onUnhandledRequest: 'bypass'` — незамоканные запросы проходят насквозь

---

## 5. Стили

- **CSS Modules** — изолированные стили на каждый компонент, нулевой рантайм
- **CSS Custom Properties** в `variables.css` — цвета, spacing, типографика, motion
- **reset.css** — нормализация браузерных стилей

---

## 6. Drag & Drop

Три сценария из README:

| Сценарий | Реализация |
|---|---|
| Файлы из ОС на AddNoteForm | `import { dropTargetForExternal } from '@atlaskit/pragmatic-drag-and-drop/external/file'` |
| Карточка на карточку → коллекция | `onDrop` с определением типа цели |
| Файлы на карточку (таймер 500-1000ms) | `setTimeout` разделяет сценарии |

Framer Motion обеспечивает:
- `layout` prop — карточки плавно сдвигаются при изменении грида
- `AnimatePresence` — анимация появления/исчезновения карточек
- `layoutId` — shared element transitions при объединении в коллекцию
