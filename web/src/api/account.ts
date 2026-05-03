import { apiFetch } from '../lib/apiClient.ts'
import type { AuthSessionResponse } from './auth.ts'

const BASE = '/api/v1/auth'

export async function fetchAuthSessions(): Promise<AuthSessionResponse[]> {
  const res = await apiFetch(`${BASE}/sessions`)
  if (!res.ok) throw new Error('Failed to load sessions')
  return res.json()
}

export async function revokeAuthSession(sessionId: string): Promise<void> {
  const res = await apiFetch(`${BASE}/sessions/${sessionId}`, { method: 'DELETE', headers: { 'Content-Type': 'application/json' } })
  if (!res.ok) throw new Error('Failed to revoke session')
}

export async function logoutAllSessions(): Promise<void> {
  const res = await apiFetch(`${BASE}/logout-all`, { method: 'POST', headers: { 'Content-Type': 'application/json' } })
  if (!res.ok) throw new Error('Failed to logout all sessions')
}
