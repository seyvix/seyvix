import type { LoaderFunctionArgs } from 'react-router'
import {
  Links,
  Meta,
  Outlet,
  Scripts,
  ScrollRestoration,
  data,
  useLoaderData,
} from 'react-router'
import './styles/reset.css'
import './styles/variables.css'
import './styles/loaders.css'
import { AppProviders } from './AppProviders'
import { loadServerAuth } from './framework/auth.server'
import { shouldRenderBeforeAuthRefresh } from './utils/authBootstrap'

export async function loader({ request }: LoaderFunctionArgs) {
  const auth = await loadServerAuth(request)
  const pathname = new URL(request.url).pathname
  const headers = new Headers(auth.headers)
  headers.set('Cache-Control', 'private, no-store, max-age=0')
  headers.set('Pragma', 'no-cache')

  return data(
    {
      user: auth.user,
      authInitialReady: Boolean(auth.user) || shouldRenderBeforeAuthRefresh(pathname),
    },
    {
      headers,
    },
  )
}

export function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <head>
        <meta charSet="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>Seyvix</title>

        <link rel="icon" type="image/png" href="/favicon-96x96.png" sizes="96x96" />
        <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
        <link rel="shortcut icon" href="/favicon.ico" />
        <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png" />
        <meta name="apple-mobile-web-app-title" content="Seyvix" />
        <link rel="manifest" href="/site.webmanifest" />

        <script src="https://telegram.org/js/telegram-web-app.js" />
        <Meta />
        <Links />
      </head>
      <body>
        {children}
        <ScrollRestoration />
        <Scripts />
      </body>
    </html>
  )
}

export default function Root() {
  const { user, authInitialReady } = useLoaderData<typeof loader>()

  return (
    <AppProviders authInitialReady={authInitialReady} authInitialUser={user}>
      <Outlet />
    </AppProviders>
  )
}
