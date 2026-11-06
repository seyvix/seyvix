import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { apiLogout, type AuthTokensResponse, type UserResponse } from '../api/auth'
import { isSessionRejection, onAuthLost, refreshSession, setAccessToken } from '../lib/apiClient'
import { accessDeniedInfo, type AccessDeniedInfo } from '../lib/apiError'
import { clearAuthenticatedBlobCache } from '../utils/authenticatedBlobUrl'
import { shouldSkipInitialRefresh } from '../utils/authBootstrap'

/**
 * - `loading`: the initial refresh is in flight.
 * - `anonymous`: no session (or it was rejected/revoked).
 * - `unavailable`: the refresh failed for a transient reason (network/5xx); the session may
 *   still be valid, so the user is offered a retry instead of being sent to the login page.
 */
export type AuthStatus = 'loading' | 'authenticated' | 'anonymous' | 'unavailable'

interface AuthContextValue {
  user: UserResponse | null
  status: AuthStatus
  /** Last allowlist denial (from login or a revoked session); shown on the auth page. */
  accessDenied: AccessDeniedInfo | null
  loginWithTokens: (tokens: AuthTokensResponse) => void
  reportAccessDenied: (info: AccessDeniedInfo | null) => void
  logout: () => Promise<void>
  retry: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient()
  const [user, setUser] = useState<UserResponse | null>(null)
  const [status, setStatus] = useState<AuthStatus>('loading')
  const [accessDenied, setAccessDenied] = useState<AccessDeniedInfo | null>(null)
  const [bootAttempt, setBootAttempt] = useState(0)

  const endSession = useCallback((denied: AccessDeniedInfo | null) => {
    setAccessToken(null)
    setUser(null)
    setStatus('anonymous')
    setAccessDenied(denied)
    queryClient.clear()
    clearAuthenticatedBlobCache()
  }, [queryClient])

  // One refresh on load. StrictMode's double effect shares the in-flight request.
  useEffect(() => {
    if (shouldSkipInitialRefresh(window.location.pathname)) {
      // The callback page is about to create the session itself.
      setStatus('anonymous')
      return
    }
    let active = true
    setStatus('loading')
    refreshSession()
      .then((tokens) => {
        if (!active) return
        setUser(tokens.user)
        setStatus('authenticated')
      })
      .catch((error: unknown) => {
        if (!active) return
        if (isSessionRejection(error)) {
          setStatus('anonymous')
          setAccessDenied(accessDeniedInfo(error))
        } else {
          console.warn('[auth] session refresh failed', error)
          setStatus('unavailable')
        }
      })
    return () => {
      active = false
    }
  }, [bootAttempt])

  useEffect(() => onAuthLost(error => endSession(accessDeniedInfo(error))), [endSession])

  const loginWithTokens = useCallback((tokens: AuthTokensResponse) => {
    setAccessToken(tokens.access_token)
    setUser(tokens.user)
    setAccessDenied(null)
    setStatus('authenticated')
  }, [])

  const logout = useCallback(async () => {
    try {
      await apiLogout()
    } catch (error) {
      // The local session is dropped regardless so the user is never stuck "logged in".
      console.error('[auth] server logout failed', error)
    } finally {
      endSession(null)
    }
  }, [endSession])

  const retry = useCallback(() => setBootAttempt(n => n + 1), [])

  const value = useMemo<AuthContextValue>(() => ({
    user,
    status,
    accessDenied,
    loginWithTokens,
    reportAccessDenied: setAccessDenied,
    logout,
    retry,
  }), [user, status, accessDenied, loginWithTokens, logout, retry])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
