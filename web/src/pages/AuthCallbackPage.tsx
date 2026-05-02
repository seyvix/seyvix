import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import { apiTelegramCode, apiTelegramResult } from '../api/auth'
import { useAuth } from '../contexts/AuthContext'
import LoaderScreen from '../components/LoaderScreen/LoaderScreen'

const EXIT_DELAY_MS = 300

export default function AuthCallbackPage() {
  const navigate = useNavigate()
  const { loginWithTokens } = useAuth()
  const [searchParams] = useSearchParams()
  const [visible, setVisible] = useState(true)

  const mountedRef = useRef(true)
  useEffect(() => () => { mountedRef.current = false }, [])

  async function handleExit(to: string) {
    setVisible(false)
    await new Promise(r => setTimeout(r, EXIT_DELAY_MS))
    if (mountedRef.current) navigate(to, { replace: true })
  }

  useEffect(() => {
    const error = searchParams.get('error')
    if (error) {
      handleExit(`/auth?error=${encodeURIComponent(error)}`)
      return
    }

    const hashParams = new URLSearchParams(window.location.hash.slice(1))
    const tgAuthResult = hashParams.get('tgAuthResult')
    if (tgAuthResult) {
      apiTelegramResult(tgAuthResult)
        .then(({ user, access_token }) => {
          loginWithTokens(user, access_token)
          handleExit('/notes')
        })
        .catch((err) => {
          console.error('[AuthCallbackPage] tgAuthResult exchange failed:', err)
          handleExit('/auth?error=telegram_code_failed')
        })
      return
    }

    const code = searchParams.get('code')
    if (!code) {
      handleExit('/auth')
      return
    }

    apiTelegramCode(code)
      .then(({ user, access_token }) => {
        loginWithTokens(user, access_token)
        handleExit('/notes')
      })
      .catch((err) => {
        console.error('[AuthCallbackPage] telegram code exchange failed:', err)
        handleExit('/auth?error=telegram_code_failed')
      })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <AnimatePresence>
      {visible && <LoaderScreen key="callback-loader" subtitle="авторизация…" />}
    </AnimatePresence>
  )
}
