import { apiFetch } from '../lib/apiClient.ts'

const BASE = '/api/v1/snapshots'

export type SnapshotFormatKey = 'screenshot' | 'webpage_html' | 'pdf' | 'markdown' | 'archive_org'

export type SnapshotFormatSettings = Record<SnapshotFormatKey, boolean>
export type SnapshotFormatOverrides = Record<SnapshotFormatKey, boolean | null>

export interface SnapshotFormatOption {
  key: SnapshotFormatKey
  label: string
  description: string
  server_enabled: boolean
}

export interface SnapshotSettingsResponse {
  available: SnapshotFormatOption[]
  effective: SnapshotFormatSettings
  overrides: SnapshotFormatOverrides
}

export async function fetchSnapshotSettings(): Promise<SnapshotSettingsResponse> {
  const res = await apiFetch(`${BASE}/settings`)
  if (!res.ok) throw new Error('Failed to load snapshot settings')
  return res.json()
}

export async function updateSnapshotSettings(
  overrides: Partial<SnapshotFormatOverrides>,
): Promise<SnapshotSettingsResponse> {
  const res = await apiFetch(`${BASE}/settings`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(overrides),
  })
  if (!res.ok) throw new Error('Failed to update snapshot settings')
  return res.json()
}
