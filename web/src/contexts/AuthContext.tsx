import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { apiLogin, apiLogout, apiRefresh, apiRegister } from '../api/auth'
import type { UserResponse } from '../api/auth'
import { configureApiClient } from '../lib/apiClient'
import { shouldSkipInitialRefresh } from '../utils/authBootstrap'

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

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserResponse | null>(null)
  const [isReady, setIsReady] = useState(false)

  // access_token живёт только в памяти
  const tokenRef = useRef<string | null>(null)

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
