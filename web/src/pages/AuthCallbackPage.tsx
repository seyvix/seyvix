import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router'
import {
  apiTelegramCode,
  apiTelegramOidcCode,
  apiTelegramResult,
  type AuthTokensResponse,
} from '../api/auth'
import { FullPageLoader } from '../components/LoaderSpinner'
import { useAuth } from '../contexts/AuthContext'
import { accessDeniedInfo } from '../lib/apiError'

/** Picks the exchange for whatever Telegram (or the dev login) put into the callback URL. */
function exchangeFromLocation(): Promise<AuthTokensResponse> | string {
  const query = new URLSearchParams(window.location.search)
  const error = query.get('error')
  if (error) return error

  // The Telegram widget sends the result in the fragment (#tgAuthResult=...).
  const tgAuthResult = new URLSearchParams(window.location.hash.slice(1)).get('tgAuthResult')
  if (tgAuthResult) return apiTelegramResult(tgAuthResult)

  const code = query.get('code')
  if (!code) return 'missing_code'
  const state = query.get('state')
  return state ? apiTelegramOidcCode(code, state) : apiTelegramCode(code)
}

export default function AuthCallbackPage() {
  const navigate = useNavigate()
  const { loginWithTokens, reportAccessDenied } = useAuth()
  // Codes are single-use: StrictMode's second effect run must not exchange them again.
  const startedRef = useRef(false)

  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true

    const exchange = exchangeFromLocation()
    if (typeof exchange === 'string') {
      navigate(exchange === 'missing_code' ? '/auth' : `/auth?error=${encodeURIComponent(exchange)}`, { replace: true })
      return
    }
    exchange
      .then((tokens) => {
        loginWithTokens(tokens)
        navigate('/notes', { replace: true })
      })
      .catch((error: unknown) => {
        const denied = accessDeniedInfo(error)
        if (denied) {
          reportAccessDenied(denied)
          navigate('/auth', { replace: true })
          return
        }
        console.error('[auth-callback] telegram auth exchange failed', error)
        navigate('/auth?error=telegram_code_failed', { replace: true })
      })
  }, [loginWithTokens, navigate, reportAccessDenied])

  return <FullPageLoader />
}
