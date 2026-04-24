import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiTelegramCode } from '../api/auth'
import { useAuth } from '../contexts/AuthContext'

export default function AuthCallbackPage() {
  const navigate = useNavigate()
  const { loginWithTokens } = useAuth()

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const code = params.get('code')
    const error = params.get('error')

    if (error) {
      navigate(`/auth?error=${encodeURIComponent(error)}`, { replace: true })
      return
    }

    if (!code) {
      navigate('/auth', { replace: true })
      return
    }

    apiTelegramCode(code)
      .then(({ user, access_token }) => {
        loginWithTokens(user, access_token)
        navigate('/notes', { replace: true })
      })
      .catch(() => {
        navigate('/auth?error=telegram_code_failed', { replace: true })
      })
  }, [navigate, loginWithTokens])

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
