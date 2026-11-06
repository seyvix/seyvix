import { apiFetch } from '../lib/apiClient.ts'
import { readJson } from '../lib/apiError.ts'

const BASE = '/api/v1/snapshots'

export type SnapshotFormatKey = 'screenshot' | 'webpage_html' | 'pdf' | 'markdown'

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
  return readJson(await apiFetch(`${BASE}/settings`), 'Не удалось загрузить настройки снапшотов')
}

export async function updateSnapshotSettings(
  overrides: Partial<SnapshotFormatOverrides>,
): Promise<SnapshotSettingsResponse> {
  const res = await apiFetch(`${BASE}/settings`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(overrides),
  })
  return readJson(res, 'Не удалось сохранить настройки снапшотов')
}
