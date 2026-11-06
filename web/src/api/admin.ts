import { apiFetch } from '../lib/apiClient.ts'

const BASE = '/api/v1/admin'

export type JobStatus = 'pending' | 'processing' | 'succeeded' | 'failed' | 'cancelled'

export interface QueueStats {
  queue: string
  kind: 'jobs' | 'events'
  pending: number
  processing: number
  failed: number
  succeeded_24h: number
  oldest_pending_seconds: number | null
}

export interface LoopStats {
  processed_total: number
  failures_total: number
  last_run_at: number | null
  last_error: string | null
  last_error_at: number | null
}

export interface WorkerInfo {
  worker_id: string
  modules: string[]
  hostname: string
  pid: number
  version: string
  started_at: string
  last_seen_at: string
  alive: boolean
  loops: Record<string, LoopStats>
}

export interface AdminOverview {
  config: {
    version: string
    environment: string
    public_url: string
    access_mode: string
    admins: number[]
    storage_backend: string
    ai_enabled: boolean
    ai_base_url: string | null
    ai_models: Record<string, string | number>
    ai_features: Record<string, boolean>
    snapshots: Record<string, boolean>
    telegram_bot_configured: boolean
  }
  host: {
    cpu_count: number | null
    load_average: number[]
    memory_total_bytes: number | null
    memory_available_bytes: number | null
    api_container_memory: { current_bytes: number | null; limit_bytes: number | null }
    disk_path: string
    disk_total_bytes: number
    disk_free_bytes: number
    api_uptime_seconds: number
  }
  database: {
    version: string
    size_bytes: number
    connections: Array<{ application: string; count: number }>
    tables: Array<{ name: string; total_bytes: number; rows: number }>
  }
  storage: { backend: string; used_bytes: number | null; files: number | null; computed_at?: number }
  queues: QueueStats[]
  workers: WorkerInfo[]
  totals: Record<string, number | null>
}

export interface QueueJob {
  id: string
  status: JobStatus
  attempts: number
  max_attempts: number
  priority: number
  run_after: string
  locked_by: string | null
  last_error: string | null
  created_at: string
  updated_at: string
  [extra: string]: unknown
}

export interface QueueJobsPage {
  queue: string
  total: number
  items: QueueJob[]
}

async function json<T>(res: Response, what: string): Promise<T> {
  if (!res.ok) throw new Error(`${what}: HTTP ${res.status}`)
  return res.json() as Promise<T>
}

export async function fetchAdminOverview(): Promise<AdminOverview> {
  return json(await apiFetch(`${BASE}/overview`), 'Не удалось загрузить обзор')
}

export async function fetchQueueJobs(
  queue: string,
  status: JobStatus | null,
  offset = 0,
): Promise<QueueJobsPage> {
  const params = new URLSearchParams({ limit: '50', offset: String(offset) })
  if (status) params.set('status', status)
  const res = await apiFetch(`${BASE}/queues/${encodeURIComponent(queue)}/jobs?${params}`)
  return json(res, 'Не удалось загрузить задачи')
}

export async function retryQueueJobs(queue: string, ids?: string[]): Promise<number> {
  const res = await apiFetch(`${BASE}/queues/${encodeURIComponent(queue)}/retry`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids: ids ?? null }),
  })
  return (await json<{ count: number }>(res, 'Не удалось перезапустить')).count
}

export async function purgeFailedJobs(queue: string): Promise<number> {
  const res = await apiFetch(`${BASE}/queues/${encodeURIComponent(queue)}/failed`, {
    method: 'DELETE',
  })
  return (await json<{ count: number }>(res, 'Не удалось удалить')).count
}

export async function refreshStorageUsage(): Promise<AdminOverview['storage']> {
  return json(await apiFetch(`${BASE}/storage?refresh=true`), 'Не удалось пересчитать')
}
