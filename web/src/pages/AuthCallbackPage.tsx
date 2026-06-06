import { useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { apiTelegramCode, apiTelegramOidcCode, apiTelegramResult } from '../api/auth'
import { useAuth } from '../contexts/AuthContext'

export default function AuthCallbackPage() {
  const navigate = useNavigate()
  const { loginWithTokens } = useAuth()
  const [searchParams] = useSearchParams()

  useEffect(() => {
    const error = searchParams.get('error')
    if (error) {
      navigate(`/auth?error=${encodeURIComponent(error)}`, { replace: true })
      return
    }

    // oauth.telegram.org sends tgAuthResult in URL fragment (#tgAuthResult=...)
    const hashParams = new URLSearchParams(window.location.hash.slice(1))
    const tgAuthResult = hashParams.get('tgAuthResult')
    if (tgAuthResult) {
      apiTelegramResult(tgAuthResult)
        .then(({ user, access_token }) => {
          loginWithTokens(user, access_token)
          navigate('/notes', { replace: true })
        })
        .catch((err) => {
          console.error('[AuthCallbackPage] tgAuthResult exchange failed:', err)
          navigate('/auth?error=telegram_code_failed', { replace: true })
        })
      return
    }

    const code = searchParams.get('code')
    const state = searchParams.get('state')
    if (!code) {
      navigate('/auth', { replace: true })
      return
    }

    const exchange = state ? apiTelegramOidcCode(code, state) : apiTelegramCode(code)
    exchange
      .then(({ user, access_token }) => {
        loginWithTokens(user, access_token)
        navigate('/notes', { replace: true })
      })
      .catch((err) => {
        console.error('[AuthCallbackPage] telegram auth code exchange failed:', err)
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
