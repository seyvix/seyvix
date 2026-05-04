import { createBrowserRouter, RouterProvider, Navigate, Outlet } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AppLayout from './components/AppLayout/AppLayout'
import { UploadProvider } from './contexts/UploadContext'
import { LocalNotesProvider } from './contexts/LocalNotesContext'
import { UploadToast } from './components/UploadToast/UploadToast'
import { SettingsProvider } from './contexts/SettingsContext'
import { AuthProvider, useAuth } from './contexts/AuthContext'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5,
      retry: 1,
    },
  },
})

// Защищённый роут: ждём bootstrap, затем проверяем авторизацию
function RequireAuth() {
  const { user, isReady } = useAuth()
  if (!isReady) return null
  if (!user) return <Navigate to="/auth" replace />
  return <Outlet />
}

// Роут для гостей: если уже залогинен — перенаправляем на /notes
function RequireGuest() {
  const { user, isReady } = useAuth()
  if (!isReady) return null
  if (user) return <Navigate to="/notes" replace />
  return <Outlet />
}

const router = createBrowserRouter([
  // Полностью открытый роут — обрабатывает Telegram redirect с ?code или ?error
  {
    path: '/auth/callback',
    lazy: async () => ({ Component: (await import('./pages/AuthCallbackPage')).default }),
  },
  // Публичный роут — без сайдбара
  {
    element: <RequireGuest />,
    children: [
      {
        path: '/auth',
        lazy: async () => ({ Component: (await import('./pages/AuthPage')).default }),
      },
    ],
  },
  // Защищённые роуты — с сайдбаром
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppLayout />,
        children: [
          {
            index: true,
            element: <Navigate to="/notes" replace />,
          },
          {
            path: '/notes',
            lazy: async () => ({ Component: (await import('./pages/NotesPage')).default }),
          },
          {
            path: '/notes/:noteId',
            lazy: async () => ({ Component: (await import('./pages/NotePage')).default }),
          },
          {
            path: '/notes/:noteId/edit',
            lazy: async () => ({ Component: (await import('./pages/NoteEditPage')).default }),
          },
          {
            path: '/categories',
            lazy: async () => ({ Component: (await import('./pages/FoldersPage')).default }),
          },
          {
            path: '/categories/*',
            lazy: async () => ({ Component: (await import('./pages/FoldersPage')).default }),
          },
          {
            path: '/trash',
            lazy: async () => ({ Component: (await import('./pages/TrashPage')).default }),
          },
          {
            path: '/folders',
            element: <Navigate to="/categories" replace />,
          },
          {
            path: '/folders/*',
            lazy: async () => ({ Component: (await import('./pages/FolderPage')).default }),
          },
          {
            path: '/settings',
            lazy: async () => ({ Component: (await import('./pages/SettingsPage')).default }),
          },
        ],
      },
    ],
  },
])

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <SettingsProvider>
          <LocalNotesProvider>
            <UploadProvider>
              <RouterProvider router={router} />
              <UploadToast />
            </UploadProvider>
          </LocalNotesProvider>
        </SettingsProvider>
      </AuthProvider>
    </QueryClientProvider>
  )
}
