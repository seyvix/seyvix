import { useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { apiTelegramCode } from '../api/auth'
import { useAuth } from '../contexts/AuthContext'

export default function AuthCallbackPage() {
  const navigate = useNavigate()
  const { loginWithTokens } = useAuth()
  const [searchParams] = useSearchParams()

  useEffect(() => {
    const code = searchParams.get('code')
    const error = searchParams.get('error')

    if (error) {
      navigate(`/auth?error=${encodeURIComponent(error)}`, { replace: true })
      return
    }

    if (!code) {
      navigate('/auth', { replace: true })
      return
    }

    // Note: AuthProvider's bootstrap apiRefresh() runs concurrently with this effect.
    // For a new user there's no refresh cookie yet, so refresh fails silently.
    // For an existing session both may succeed — the last setUser() call wins, which is fine.
    apiTelegramCode(code)
      .then(({ user, access_token }) => {
        loginWithTokens(user, access_token)
        navigate('/notes', { replace: true })
      })
      .catch((err) => {
        console.error('[AuthCallbackPage] telegram code exchange failed:', err)
        navigate('/auth?error=telegram_code_failed', { replace: true })
      })
  }, [navigate, loginWithTokens, searchParams])

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
      }}
    >
      <p style={{ color: 'var(--color-text-secondary, #888)', fontFamily: 'inherit' }}>
        Авторизация…
      </p>
    </div>
  )
}
