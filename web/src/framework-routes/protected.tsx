import { Navigate } from 'react-router'
import AppLayout from '../components/AppLayout/AppLayout'
import { FullPageLoader } from '../components/LoaderSpinner'
import { useAuth } from '../contexts/AuthContext'

export default function ProtectedRoute() {
  const { user, status, retry } = useAuth()

  if (status === 'loading') return <FullPageLoader />
  if (status === 'unavailable') {
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
        <h1 style={{ fontSize: 22 }}>Сервер недоступен</h1>
        <p style={{ color: 'var(--color-text-secondary, #888)' }}>
          Не удалось проверить сессию. Проверь подключение и попробуй ещё раз.
        </p>
        <button type="button" onClick={retry}>Повторить</button>
      </main>
    )
  }
  if (!user) return <Navigate to="/auth" replace />
  return <AppLayout />
}
