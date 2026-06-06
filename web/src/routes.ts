import {
  index,
  layout,
  route,
  type RouteConfig,
} from '@react-router/dev/routes'

export default [
  route('health', './framework-routes/health.ts'),
  route('auth/callback', './framework-routes/auth-callback.tsx'),
  layout('./framework-routes/auth-guest.tsx', [
    route('auth', './framework-routes/auth.tsx'),
  ]),
  layout('./framework-routes/protected.tsx', [
    index('./framework-routes/redirect-notes.tsx'),
    route('notes', './framework-routes/notes.tsx'),
    route('notes/:noteId', './framework-routes/note.tsx'),
    route('notes/:noteId/edit', './framework-routes/note-edit.tsx'),
    route('categories', './framework-routes/folders.tsx'),
    route('categories/*', './framework-routes/folders-catchall.tsx'),
    route('trash', './framework-routes/trash.tsx'),
    route('folders', './framework-routes/redirect-categories.tsx'),
    route('folders/*', './framework-routes/folder.tsx'),
    route('settings', './framework-routes/settings.tsx'),
  ]),
] satisfies RouteConfig
