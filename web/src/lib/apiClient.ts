/**
 * Fetch-обёртка для защищённых запросов к API.
 * - Добавляет Authorization: Bearer <accessToken>
 * - При 401 пробует refresh и повторяет запрос один раз
 * - При провале refresh вызывает onUnauthenticated()
 */

import { apiRefresh } from '../api/auth.ts'

type GetToken = () => string | null
type SetToken = (token: string) => void
type OnUnauthenticated = () => void

let getToken: GetToken = () => null
let setToken: SetToken = () => {}
let onUnauthenticated: OnUnauthenticated = () => {}
let refreshPromise: ReturnType<typeof apiRefresh> | null = null

export function configureApiClient(cfg: {
  getToken: GetToken
  setToken: SetToken
  onUnauthenticated: OnUnauthenticated
}) {
  getToken = cfg.getToken
  setToken = cfg.setToken
  onUnauthenticated = cfg.onUnauthenticated
}

export async function refreshApiToken() {
  refreshPromise ??= apiRefresh().finally(() => {
    refreshPromise = null
  })
  const refreshed = await refreshPromise
  setToken(refreshed.access_token)
  return refreshed
}

export async function apiFetch(input: RequestInfo, init: RequestInit = {}): Promise<Response> {
  let token = getToken()
  if (!token && refreshPromise) {
    try {
      const refreshed = await refreshPromise
      token = refreshed.access_token
    } catch {
      token = null
    }
  }

  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(input, { ...init, headers, credentials: init.credentials ?? 'include' })

  if (res.status !== 401) return res

  // Concurrent 401 responses must share refresh because the backend rotates refresh tokens.
  try {
    const refreshed = await refreshApiToken()

    const retryHeaders = new Headers(init.headers)
    retryHeaders.set('Authorization', `Bearer ${refreshed.access_token}`)
    return fetch(input, { ...init, headers: retryHeaders, credentials: init.credentials ?? 'include' })
  } catch {
    onUnauthenticated()
    return res
  }
}
