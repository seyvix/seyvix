const BASE = '/api/v1/auth'

export interface UserResponse {
  id: string
  telegram_id: string
  telegram_username: string | null
  telegram_photo_url: string | null
  avatar_url?: string | null
  display_name: string
  is_active: boolean
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

export interface ApiError {
  code: string
  message: string
  details: unknown
}

export class AuthApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

async function parseError(res: Response): Promise<AuthApiError> {
  try {
    const body = await res.json()
    const err: ApiError = body.error ?? body
    return new AuthApiError(res.status, err.code ?? 'unknown_error', err.message ?? 'Unknown error')
  } catch {
    return new AuthApiError(res.status, 'unknown_error', res.statusText)
  }
}

export async function apiRegister(
  email: string,
  display_name: string,
  password: string,
): Promise<AuthTokensResponse> {
  const res = await fetch(`${BASE}/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, display_name, password }),
    credentials: 'include',
  })
  if (!res.ok) throw await parseError(res)
  return res.json()
}

export async function apiLogin(
  email: string,
  password: string,
): Promise<AuthTokensResponse> {
  const res = await fetch(`${BASE}/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
    credentials: 'include',
  })
  if (!res.ok) throw await parseError(res)
  return res.json()
}

export async function apiRefresh(): Promise<AuthTokensResponse> {
  const res = await fetch(`${BASE}/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
  })
  if (!res.ok) throw await parseError(res)
  return res.json()
}

export async function apiLogout(): Promise<void> {
  await fetch(`${BASE}/logout`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
  })
}

export async function apiTelegramResult(tgAuthResult: string): Promise<AuthTokensResponse> {
  const res = await fetch(`${BASE}/telegram-result`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tg_auth_result: tgAuthResult }),
    credentials: 'include',
  })
  if (!res.ok) throw await parseError(res)
  return res.json()
}

export async function apiTelegramCode(code: string): Promise<AuthTokensResponse> {
  const res = await fetch(`${BASE}/telegram-code`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
    credentials: 'include',
  })
  if (!res.ok) throw await parseError(res)
  return res.json()
}
