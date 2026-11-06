import { ensureOk, readJson } from '../lib/apiError.ts'

const BASE = '/api/v1/auth'

export interface UserResponse {
  id: string
  telegram_id: string
  telegram_username: string | null
  telegram_photo_url: string | null
  avatar_url?: string | null
  display_name: string
  is_active: boolean
  is_admin: boolean
}

export interface AuthSessionResponse {
  id: string
  created_at: string
  last_used_at: string | null
  expires_at: string
  user_agent: string | null
  ip_address: string | null
  is_current: boolean
}

export interface AuthTokensResponse {
  user: UserResponse
  access_token: string
  token_type: string
}

/** Login exchanges are unauthenticated POSTs that set the refresh cookie and return tokens. */
async function exchange(path: string, body: Record<string, string>, failure: string) {
  const res = await fetch(`${BASE}/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body),
  })
  return readJson<AuthTokensResponse>(res, failure)
}

export function apiTelegramResult(tgAuthResult: string): Promise<AuthTokensResponse> {
  return exchange('telegram-result', { tg_auth_result: tgAuthResult }, 'Telegram login failed')
}

export function apiTelegramWebApp(initData: string): Promise<AuthTokensResponse> {
  return exchange('telegram-web-app', { init_data: initData }, 'Telegram Mini App login failed')
}

export function apiTelegramCode(code: string): Promise<AuthTokensResponse> {
  return exchange('telegram-code', { code }, 'Telegram login failed')
}

export function apiTelegramOidcCode(code: string, state: string): Promise<AuthTokensResponse> {
  return exchange('telegram-oidc-code', { code, state }, 'Telegram login failed')
}

/** Revokes the current refresh session server-side and clears the refresh cookie. */
export async function apiLogout(): Promise<void> {
  const res = await fetch(`${BASE}/logout`, { method: 'POST' })
  await ensureOk(res, 'Logout failed')
}
