import { apiFetch } from '../lib/apiClient.ts'
import { ensureOk, readJson } from '../lib/apiError.ts'
import type { AuthSessionResponse } from './auth.ts'

const AUTH = '/api/v1/auth'
const ADMIN_ACCESS = '/api/v1/admin/access'

export async function fetchAuthSessions(): Promise<AuthSessionResponse[]> {
  return readJson(await apiFetch(`${AUTH}/sessions`), 'Не удалось загрузить сессии')
}

export async function revokeAuthSession(sessionId: string): Promise<void> {
  const res = await apiFetch(`${AUTH}/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
  await ensureOk(res, 'Не удалось завершить сессию')
}

export async function logoutAllSessions(): Promise<void> {
  await ensureOk(await apiFetch(`${AUTH}/logout-all`, { method: 'POST' }), 'Не удалось завершить сессии')
}

export interface AccessGrant {
  id: string
  telegram_user_id: number | null
  username: string | null
  note: string | null
  created_at: string
  last_login_at: string | null
  display_name: string | null
}

export interface AccessOverview {
  mode: 'allowlist' | 'open'
  admins: number[]
  items: AccessGrant[]
}

export interface AccessGrantInput {
  telegram_user_id?: number
  username?: string
  note?: string
}

export const ACCESS_QUERY_KEY = ['admin-access'] as const

export async function fetchAccessOverview(): Promise<AccessOverview> {
  return readJson(await apiFetch(ADMIN_ACCESS), 'Не удалось загрузить список доступа')
}

export async function createAccessGrant(input: AccessGrantInput): Promise<AccessGrant> {
  const res = await apiFetch(ADMIN_ACCESS, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  return readJson(res, 'Не удалось выдать доступ')
}

export async function deleteAccessGrant(grantId: string): Promise<void> {
  const res = await apiFetch(`${ADMIN_ACCESS}/${encodeURIComponent(grantId)}`, { method: 'DELETE' })
  await ensureOk(res, 'Не удалось отозвать доступ')
}

/**
 * Parses the admin's "who to allow" input: a numeric Telegram ID, or a username with or
 * without the leading `@` (also accepts t.me links). Returns null for anything else.
 */
export function parseAccessTarget(raw: string): Pick<AccessGrantInput, 'telegram_user_id' | 'username'> | null {
  const value = raw.trim().replace(/^(https?:\/\/)?(t\.me|telegram\.me)\//i, '')
  if (/^\d{3,15}$/.test(value)) return { telegram_user_id: Number(value) }
  const username = value.replace(/^@/, '')
  if (/^[A-Za-z][A-Za-z0-9_]{4,31}$/.test(username)) return { username }
  return null
}
