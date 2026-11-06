import type { Config } from '@react-router/dev/config'

// SPA mode: `react-router build` emits a static `build/client` (index.html + hashed assets)
// that Caddy serves directly; there is no Node runtime in production.
export default {
  appDirectory: 'src',
  ssr: false,
} satisfies Config
