import { defineConfig } from 'vite'
import { reactRouter } from '@react-router/dev/vite'

// Long-lived vendor groups. Everything not listed here is left to Rollup so it lands in the
// (lazily loaded) route or component chunk that actually imports it.
const VENDOR_CHUNKS: Array<[chunk: string, packages: RegExp]> = [
  ['react', /\/node_modules\/(react|react-dom|scheduler|react-router|cookie|set-cookie-parser)\//],
  ['react-query', /\/node_modules\/@tanstack\//],
  ['icons', /\/node_modules\/lucide-react\//],
  ['rich-text-editor', /\/node_modules\/(@tiptap|prosemirror-[^/]+|orderedmap|rope-sequence|w3c-keyname|linkifyjs|markdown-it|@popperjs|tippy\.js)\//],
  ['motion', /\/node_modules\/(framer-motion|motion-dom|motion-utils)\//],
  ['muuri', /\/node_modules\/muuri\//],
]

export default defineConfig({
  plugins: [reactRouter()],
  ssr: {
    // The SPA build pre-renders the root route in Node; this package ships untranspiled ESM.
    noExternal: ['@atlaskit/pragmatic-drag-and-drop'],
  },
  build: {
    reportCompressedSize: false,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('/node_modules/')) return undefined
          for (const [chunk, pattern] of VENDOR_CHUNKS) {
            if (pattern.test(id)) return chunk
          }
          return undefined
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
