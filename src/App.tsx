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
