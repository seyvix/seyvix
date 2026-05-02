import { createBrowserRouter, RouterProvider, Navigate, Outlet } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import AppLayout from './components/AppLayout/AppLayout'
import { UploadProvider } from './contexts/UploadContext'
import { LocalNotesProvider } from './contexts/LocalNotesContext'
import { UploadToast } from './components/UploadToast/UploadToast'
import { SettingsProvider } from './contexts/SettingsContext'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import LoaderScreen from './components/LoaderScreen/LoaderScreen'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5,
      retry: 1,
    },
  },
})

function RequireAuth() {
  const { user, isReady } = useAuth()
  if (!isReady) return null
  if (!user) return <Navigate to="/auth" replace />
  return <Outlet />
}

function RequireGuest() {
  const { user, isReady } = useAuth()
  if (!isReady) return null
  if (user) return <Navigate to="/notes" replace />
  return <Outlet />
}

const router = createBrowserRouter([
  {
    path: '/auth/callback',
    lazy: async () => ({ Component: (await import('./pages/AuthCallbackPage')).default }),
  },
  {
    element: <RequireGuest />,
    children: [
      {
        path: '/auth',
        lazy: async () => ({ Component: (await import('./pages/AuthPage')).default }),
      },
    ],
  },
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
        ],
      },
    ],
  },
])

function AppInner() {
  const { isReady } = useAuth()

  return (
    <AnimatePresence mode="wait">
      {!isReady ? (
        <LoaderScreen key="bootstrap" />
      ) : (
        <motion.div
          key="app"
          style={{ height: '100%' }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.2 }}
        >
          <RouterProvider router={router} />
          <UploadToast />
        </motion.div>
      )}
    </AnimatePresence>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <SettingsProvider>
          <LocalNotesProvider>
            <UploadProvider>
              <AppInner />
            </UploadProvider>
          </LocalNotesProvider>
        </SettingsProvider>
      </AuthProvider>
    </QueryClientProvider>
  )
}
