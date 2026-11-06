/**
 * Session-aware fetch for protected API calls.
 *
 * - The access token lives only in this module's memory (never in storage).
 * - The refresh token is an httponly cookie; `refreshSession()` exchanges it for a new access
 *   token. Concurrent callers share one in-flight refresh because the backend rotates refresh
 *   tokens (a second parallel refresh would invalidate the first).
 * - On 401 a request is retried once after a refresh. When the refresh itself is rejected
 *   (401, or 403 when access was revoked) every `onAuthLost` listener is notified.
 */

import type { AuthTokensResponse } from '../api/auth.ts'
import { ApiError, toApiError } from './apiError.ts'

const REFRESH_URL = '/api/v1/auth/refresh'

let accessToken: string | null = null
let refreshPromise: Promise<AuthTokensResponse> | null = null
const authLostListeners = new Set<(error: ApiError) => void>()

export function setAccessToken(token: string | null): void {
  accessToken = token
}

/** Subscribe to "the session is gone" (refresh rejected). Returns an unsubscribe function. */
export function onAuthLost(listener: (error: ApiError) => void): () => void {
  authLostListeners.add(listener)
  return () => {
    authLostListeners.delete(listener)
  }
}

/** True when the refresh was rejected by the server (as opposed to a network/5xx failure). */
export function isSessionRejection(error: unknown): error is ApiError {
  return error instanceof ApiError && (error.status === 401 || error.status === 403)
}

async function requestRefresh(): Promise<AuthTokensResponse> {
  const res = await fetch(REFRESH_URL, {
    method: 'POST',
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) throw await toApiError(res, 'Session refresh failed')
  return (await res.json()) as AuthTokensResponse
}

/** Exchanges the refresh cookie for a new access token (single shared request). */
export function refreshSession(): Promise<AuthTokensResponse> {
  refreshPromise ??= requestRefresh()
    .then((tokens) => {
      accessToken = tokens.access_token
      return tokens
    })
    .finally(() => {
      refreshPromise = null
    })
  return refreshPromise
}

/**
 * Returns a usable token after `staleToken` was rejected, or null when no session can be
 * restored. Server-side rejection ends the session; transient failures leave it untouched.
 */
async function recoverToken(staleToken: string | null): Promise<string | null> {
  if (accessToken && accessToken !== staleToken) return accessToken
  try {
    return (await refreshSession()).access_token
  } catch (error) {
    if (isSessionRejection(error)) {
      accessToken = null
      for (const listener of authLostListeners) listener(error)
    }
    return null
  }
}

function send(input: RequestInfo | URL, init: RequestInit, token: string | null): Promise<Response> {
  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  return fetch(input, { ...init, headers })
}

export async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const token = accessToken ?? await recoverToken(null)
  const res = await send(input, init, token)
  // No token means recovery already failed for this request; don't refresh twice.
  if (res.status !== 401 || token === null) return res

  const freshToken = await recoverToken(token)
  if (!freshToken) return res
  return send(input, init, freshToken)
}
