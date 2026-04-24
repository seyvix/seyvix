import { createBrowserRouter, RouterProvider, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AppLayout from './components/AppLayout/AppLayout'
import { UploadProvider } from './contexts/UploadContext'
import { UploadToast } from './components/UploadToast/UploadToast'
import { SettingsProvider } from './contexts/SettingsContext'

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
])

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <SettingsProvider>
        <UploadProvider>
          <RouterProvider router={router} />
          <UploadToast />
        </UploadProvider>
      </SettingsProvider>
    </QueryClientProvider>
  )
}
