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

export function configureApiClient(cfg: {
  getToken: GetToken
  setToken: SetToken
  onUnauthenticated: OnUnauthenticated
}) {
  getToken = cfg.getToken
  setToken = cfg.setToken
  onUnauthenticated = cfg.onUnauthenticated
}

export async function apiFetch(input: RequestInfo, init: RequestInit = {}): Promise<Response> {
  const token = getToken()

  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(input, { ...init, headers })

  if (res.status !== 401) return res

  // Попытка refresh
  try {
    const refreshed = await apiRefresh()
    setToken(refreshed.access_token)

    const retryHeaders = new Headers(init.headers)
    retryHeaders.set('Authorization', `Bearer ${refreshed.access_token}`)
    return fetch(input, { ...init, headers: retryHeaders })
  } catch {
    onUnauthenticated()
    return res
  }
}
