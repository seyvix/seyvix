import { defineConfig } from 'vite'
import { reactRouter } from '@react-router/dev/vite'

export default defineConfig({
  plugins: [reactRouter()],
  ssr: {
    noExternal: ['@atlaskit/pragmatic-drag-and-drop'],
  },
  build: {
    minify: process.env.VITE_BUILD_MINIFY === 'false' ? false : 'esbuild',
    reportCompressedSize: false,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) {
            if (id.includes('/src/pages/NotesPage.') || id.includes('/src/components/NoteGrid/')) {
              return 'notes-browser'
            }
            if (id.includes('/src/pages/NotePage.') || id.includes('/src/components/PDFViewer/') || id.includes('/src/components/HtmlSnapshotViewer/')) {
              return 'note-detail'
            }
            if (id.includes('/src/pages/AuthPage.') || id.includes('/src/pages/AuthCallbackPage.')) {
              return 'auth'
            }
            if (id.includes('/src/pages/SettingsPage.') || id.includes('/src/pages/TrashPage.') || id.includes('/src/pages/FoldersPage.') || id.includes('/src/pages/FolderPage.')) {
              return 'settings-and-collections'
            }
            return undefined
          }

          if (id.includes('/node_modules/react-router/') || id.includes('/node_modules/@remix-run/router/')) return 'router'
          if (id.includes('/node_modules/react-dom/') || id.includes('/node_modules/react/')) return 'react'
          if (id.includes('/node_modules/scheduler/')) return 'scheduler'
          if (id.includes('@tanstack/react-query')) return 'react-query'
          if (id.includes('framer-motion')) return 'framer-motion'
          if (id.includes('lucide-react')) return 'icons'
          if (id.includes('@tiptap') || id.includes('prosemirror')) return 'rich-text-editor'
          if (id.includes('@xyflow/react')) return 'graph'
          if (id.includes('muuri')) return 'muuri'
          return 'vendor'
        },
      },
    },
  },
  server: {
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
