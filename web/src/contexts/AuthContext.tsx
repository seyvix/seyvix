import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { apiLogin, apiLogout, apiRefresh, apiRegister } from '../api/auth'
import type { UserResponse } from '../api/auth'
import { configureApiClient, refreshApiToken } from '../lib/apiClient'
import { shouldRenderBeforeAuthRefresh, shouldSkipInitialRefresh } from '../utils/authBootstrap'

interface AuthContextValue {
  user: UserResponse | null
  isReady: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, display_name: string, password: string) => Promise<void>
  logout: () => Promise<void>
  loginWithTokens: (user: UserResponse, accessToken: string) => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

interface AuthProviderProps {
  children: React.ReactNode
  initialIsReady?: boolean
  initialUser?: UserResponse | null
  initialAccessToken?: string | null
}

export function AuthProvider({
  children,
  initialIsReady,
  initialUser = null,
  initialAccessToken = null,
}: AuthProviderProps) {
  const [user, setUser] = useState<UserResponse | null>(initialUser)
  const [isReady, setIsReady] = useState(() => (
    initialIsReady ?? (
      Boolean(initialUser && initialAccessToken) ||
      typeof window !== 'undefined' &&
      shouldRenderBeforeAuthRefresh(window.location.pathname)
    )
  ))

  // access_token живёт только в памяти
  const tokenRef = useRef<string | null>(initialAccessToken)

  // Настраиваем apiClient сразу — он будет использоваться в api/notes.ts
  useEffect(() => {
    configureApiClient({
      getToken: () => tokenRef.current,
      setToken: (t) => { tokenRef.current = t },
      onUnauthenticated: () => {
        tokenRef.current = null
        setUser(null)
      },
    })
  }, [])

  // Bootstrap: пробуем refresh при старте приложения
  useEffect(() => {
    if (initialUser) {
      setIsReady(true)
      if (!initialAccessToken) {
        refreshApiToken()
          .then(({ user, access_token }) => {
            tokenRef.current = access_token
            setUser(user)
          })
          .catch(() => {
            tokenRef.current = null
            setUser(null)
          })
      }
      return
    }

    if (shouldSkipInitialRefresh(window.location.pathname)) {
      setIsReady(true)
      return
    }

    apiRefresh()
      .then(({ user, access_token }) => {
        tokenRef.current = access_token
        setUser(user)
      })
      .catch(() => {
        // refresh не удался — пользователь не авторизован, это нормально
      })
      .finally(() => {
        setIsReady(true)
      })
  }, [])

  async function login(email: string, password: string) {
    const { user, access_token } = await apiLogin(email, password)
    tokenRef.current = access_token
    setUser(user)
  }

  async function register(email: string, display_name: string, password: string) {
    const { user, access_token } = await apiRegister(email, display_name, password)
    tokenRef.current = access_token
    setUser(user)
  }

  async function logout() {
    await apiLogout()
    tokenRef.current = null
    setUser(null)
  }

  // useCallback даёт стабильную ссылку — useEffect в AuthCallbackPage не зациклится
  const loginWithTokens = useCallback((user: UserResponse, accessToken: string) => {
    tokenRef.current = accessToken
    setUser(user)
  }, [])

  return (
    <AuthContext.Provider value={{ user, isReady, login, register, logout, loginWithTokens }}>
      {children}
    </AuthContext.Provider>
  )
}
