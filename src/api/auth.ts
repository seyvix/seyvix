const BASE = '/api/v1/auth'

export interface UserResponse {
  id: string
  email: string
  display_name: string
  is_active: boolean
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
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message)
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
    credentials: 'include',
  })
  if (!res.ok) throw await parseError(res)
  return res.json()
}

export async function apiLogout(): Promise<void> {
  await fetch(`${BASE}/logout`, {
    method: 'POST',
    credentials: 'include',
  })
}
