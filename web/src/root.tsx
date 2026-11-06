import {
  Links,
  Meta,
  Outlet,
  Scripts,
  ScrollRestoration,
  isRouteErrorResponse,
} from 'react-router'
import type { Route } from './+types/root'
import './styles/reset.css'
import './styles/variables.css'
import './styles/loaders.css'
import { AppProviders } from './AppProviders'
import { FullPageLoader } from './components/LoaderSpinner'

export function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <head>
        <meta charSet="UTF-8" />
        <meta
          name="viewport"
          content="width=device-width, initial-scale=1.0, viewport-fit=cover"
        />
        <title>Seyvix</title>

        <link rel="icon" type="image/png" href="/favicon-96x96.png" sizes="96x96" />
        <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
        <link rel="shortcut icon" href="/favicon.ico" />
        <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png" />
        <link rel="manifest" href="/site.webmanifest" />
        <meta name="apple-mobile-web-app-title" content="Seyvix" />

        {/* Deferred classic scripts run before the (deferred) module entry, in document order,
            so `window.Telegram.WebApp` is available when the app boots without blocking parsing. */}
        <script src="https://telegram.org/js/telegram-web-app.js?62" defer />
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

/** Rendered into the static index.html at build time and shown until the bundle boots. */
export function HydrateFallback() {
  return <FullPageLoader />
}

export default function Root() {
  return (
    <AppProviders>
      <Outlet />
    </AppProviders>
  )
}

export function ErrorBoundary({ error }: Route.ErrorBoundaryProps) {
  const title = isRouteErrorResponse(error) && error.status === 404
    ? 'Страница не найдена'
    : 'Что-то пошло не так'
  if (!isRouteErrorResponse(error)) console.error('[root] unhandled error', error)

  return (
    <main
      style={{
        minHeight: '100dvh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 16,
        padding: 24,
        textAlign: 'center',
      }}
    >
      <h1 style={{ fontSize: 22 }}>{title}</h1>
      <div style={{ display: 'flex', gap: 12 }}>
        <a href="/notes">К заметкам</a>
        <button type="button" onClick={() => window.location.reload()}>
          Обновить страницу
        </button>
      </div>
    </main>
  )
}
