import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Navigate } from 'react-router'
import {
  fetchAdminOverview,
  fetchQueueJobs,
  purgeFailedJobs,
  refreshStorageUsage,
  retryQueueJobs,
  type AdminOverview,
  type JobStatus,
  type QueueStats,
  type WorkerInfo,
} from '../api/admin'
import { useAuth } from '../contexts/AuthContext'
import styles from './AdminPage.module.css'

const OVERVIEW_KEY = ['admin', 'overview'] as const

const QUEUE_LABELS: Record<string, string> = {
  snapshot_jobs: 'Снапшоты',
  vectorization_jobs: 'Векторизация',
  tagging_jobs: 'Теги',
  taxonomy_classification_jobs: 'Категории',
  'events:snapshots': 'События → снапшоты',
  'events:vectorization': 'События → векторизация',
  'events:tags': 'События → теги',
  'events:taxonomy': 'События → категории',
}

function formatBytes(value: number | null | undefined): string {
  if (value == null) return '—'
  const units = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ']
  let size = value
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  return `${size.toFixed(size >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return '—'
  if (seconds < 60) return `${seconds} с`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} мин`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} ч`
  return `${Math.floor(seconds / 86400)} д`
}

function formatTime(value: string | number | null | undefined): string {
  if (value == null) return '—'
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value)
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(date)
}

function percent(part: number | null, total: number | null): number {
  if (!part || !total) return 0
  return Math.min(100, Math.round((part / total) * 100))
}

function Meter({ label, used, total, hint }: { label: string; used: number | null; total: number | null; hint: string }) {
  const value = percent(used, total)
  const tone = value > 90 ? styles.meterDanger : value > 75 ? styles.meterWarn : ''
  return (
    <div className={styles.metric}>
      <span className={styles.metricLabel}>{label}</span>
      <strong>{value}%</strong>
      <div className={styles.meter}>
        <div className={`${styles.meterFill} ${tone}`} style={{ width: `${value}%` }} />
      </div>
      <small>{hint}</small>
    </div>
  )
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className={styles.metric}>
      <span className={styles.metricLabel}>{label}</span>
      <strong>{value}</strong>
      {hint ? <small>{hint}</small> : null}
    </div>
  )
}

function HostSection({ data }: { data: AdminOverview }) {
  const { host, database, storage, totals } = data
  const memUsed =
    host.memory_total_bytes != null && host.memory_available_bytes != null
      ? host.memory_total_bytes - host.memory_available_bytes
      : null
  const diskUsed = host.disk_total_bytes - host.disk_free_bytes
  return (
    <section className={styles.grid}>
      <Meter
        label="Память сервера"
        used={memUsed}
        total={host.memory_total_bytes}
        hint={`${formatBytes(memUsed)} из ${formatBytes(host.memory_total_bytes)}`}
      />
      <Meter
        label="Диск"
        used={diskUsed}
        total={host.disk_total_bytes}
        hint={`свободно ${formatBytes(host.disk_free_bytes)}`}
      />
      <Stat
        label="Нагрузка CPU"
        value={host.load_average.join(' · ')}
        hint={`${host.cpu_count ?? '?'} ядер, 1/5/15 мин`}
      />
      <Stat label="База данных" value={formatBytes(database.size_bytes)} hint={`PostgreSQL ${database.version}`} />
      <Stat
        label="Файлы"
        value={formatBytes(storage.used_bytes)}
        hint={storage.files != null ? `${storage.files} файлов · ${storage.backend}` : storage.backend}
      />
      <Stat
        label="Заметки"
        value={String(totals.notes ?? '—')}
        hint={`+${totals.notes_last_24h ?? 0} за сутки · ${totals.notes_in_trash ?? 0} в корзине`}
      />
      <Stat
        label="Пользователи"
        value={String(totals.users ?? '—')}
        hint={`${totals.active_sessions ?? 0} активных сессий`}
      />
      <Stat
        label="API"
        value={formatDuration(host.api_uptime_seconds)}
        hint={`аптайм · память ${formatBytes(host.api_container_memory.current_bytes)}`}
      />
    </section>
  )
}

function WorkersSection({ workers }: { workers: WorkerInfo[] }) {
  return (
    <section className={styles.panel}>
      <header className={styles.panelHeader}>
        <h2>Воркеры</h2>
        <span className={styles.muted}>{workers.length === 0 ? 'ни одного живого воркера' : `${workers.length} процесс(ов)`}</span>
      </header>
      {workers.map((worker) => (
        <div key={worker.worker_id} className={styles.worker}>
          <div className={styles.workerHead}>
            <span className={worker.alive ? styles.dotOk : styles.dotBad} />
            <strong>{worker.modules.join(', ')}</strong>
            <span className={styles.muted}>
              {worker.hostname} · pid {worker.pid} · v{worker.version} · пульс {formatTime(worker.last_seen_at)}
            </span>
          </div>
          <div className={styles.loops}>
            {Object.entries(worker.loops).map(([name, loop]) => (
              <div key={name} className={styles.loop} title={loop.last_error ?? undefined}>
                <span>{name}</span>
                <small>
                  обработано {loop.processed_total}
                  {loop.failures_total > 0 ? ` · ошибок ${loop.failures_total}` : ''}
                </small>
                {loop.last_error ? (
                  <small className={styles.error}>
                    {formatTime(loop.last_error_at)}: {loop.last_error}
                  </small>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ))}
    </section>
  )
}

function QueueJobs({ queue, onChanged }: { queue: string; onChanged: () => void }) {
  const [status, setStatus] = useState<JobStatus | null>('failed')
  const jobs = useQuery({
    queryKey: ['admin', 'queue', queue, status],
    queryFn: () => fetchQueueJobs(queue, status),
  })
  const retry = useMutation({
    mutationFn: (ids?: string[]) => retryQueueJobs(queue, ids),
    onSuccess: () => {
      void jobs.refetch()
      onChanged()
    },
  })
  const purge = useMutation({
    mutationFn: () => purgeFailedJobs(queue),
    onSuccess: () => {
      void jobs.refetch()
      onChanged()
    },
  })

  return (
    <div className={styles.jobs}>
      <div className={styles.jobsToolbar}>
        <div className={styles.segmented}>
          {(['failed', 'pending', 'processing', 'succeeded', null] as const).map((value) => (
            <button
              key={value ?? 'all'}
              type="button"
              className={status === value ? styles.segmentActive : ''}
              onClick={() => setStatus(value)}
            >
              {value ?? 'все'}
            </button>
          ))}
        </div>
        <div className={styles.actions}>
          <button type="button" className={styles.button} disabled={retry.isPending} onClick={() => retry.mutate(undefined)}>
            Перезапустить все упавшие
          </button>
          <button
            type="button"
            className={styles.dangerButton}
            disabled={purge.isPending}
            onClick={() => {
              if (window.confirm('Удалить все упавшие задачи этой очереди?')) purge.mutate()
            }}
          >
            Удалить упавшие
          </button>
        </div>
      </div>
      {jobs.isLoading ? <p className={styles.muted}>Загрузка…</p> : null}
      {jobs.error ? <p className={styles.error}>{String(jobs.error)}</p> : null}
      {jobs.data && jobs.data.items.length === 0 ? <p className={styles.muted}>Пусто</p> : null}
      {jobs.data?.items.map((job) => (
        <div key={job.id} className={styles.job}>
          <div className={styles.jobHead}>
            <code>{job.id.slice(0, 8)}</code>
            <span className={styles.badge} data-status={job.status}>{job.status}</span>
            <span className={styles.muted}>
              попыток {job.attempts}/{job.max_attempts} · {formatTime(job.updated_at)}
              {typeof job.job_type === 'string' ? ` · ${job.job_type}` : ''}
              {typeof job.content_object_id === 'string' ? ` · заметка ${job.content_object_id.slice(0, 8)}` : ''}
            </span>
            {job.status === 'failed' ? (
              <button type="button" className={styles.linkButton} onClick={() => retry.mutate([job.id])}>
                повторить
              </button>
            ) : null}
          </div>
          {job.last_error ? <pre className={styles.errorBox}>{job.last_error}</pre> : null}
        </div>
      ))}
      {jobs.data && jobs.data.total > jobs.data.items.length ? (
        <p className={styles.muted}>Показаны последние {jobs.data.items.length} из {jobs.data.total}</p>
      ) : null}
    </div>
  )
}

function QueuesSection({ queues, onChanged }: { queues: QueueStats[]; onChanged: () => void }) {
  const [open, setOpen] = useState<string | null>(null)
  return (
    <section className={styles.panel}>
      <header className={styles.panelHeader}>
        <h2>Очереди</h2>
        <span className={styles.muted}>упавшие задачи — это dead letters, их можно перезапустить</span>
      </header>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Очередь</th>
            <th>Ждут</th>
            <th>В работе</th>
            <th>Упали</th>
            <th>Готово за 24ч</th>
            <th>Старейшая</th>
          </tr>
        </thead>
        <tbody>
          {queues.map((queue) => (
            <QueueRow
              key={queue.queue}
              queue={queue}
              open={open === queue.queue}
              onToggle={() => setOpen(open === queue.queue ? null : queue.queue)}
              onChanged={onChanged}
            />
          ))}
        </tbody>
      </table>
    </section>
  )
}

function QueueRow({
  queue,
  open,
  onToggle,
  onChanged,
}: {
  queue: QueueStats
  open: boolean
  onToggle: () => void
  onChanged: () => void
}) {
  const stuck = (queue.oldest_pending_seconds ?? 0) > 600
  return (
    <>
      <tr className={styles.clickable} onClick={onToggle}>
        <td>
          {QUEUE_LABELS[queue.queue] ?? queue.queue}
          <small className={styles.muted}> {queue.queue}</small>
        </td>
        <td>{queue.pending}</td>
        <td>{queue.processing}</td>
        <td className={queue.failed > 0 ? styles.error : ''}>{queue.failed}</td>
        <td>{queue.succeeded_24h}</td>
        <td className={stuck ? styles.error : ''}>{formatDuration(queue.oldest_pending_seconds)}</td>
      </tr>
      {open ? (
        <tr>
          <td colSpan={6}>
            <QueueJobs queue={queue.queue} onChanged={onChanged} />
          </td>
        </tr>
      ) : null}
    </>
  )
}

function ConfigSection({ data }: { data: AdminOverview }) {
  const { config, database } = data
  const flags = { ...config.ai_features, ...Object.fromEntries(Object.entries(config.snapshots).map(([k, v]) => [`snapshot ${k}`, v])) }
  return (
    <div className={styles.columns}>
      <section className={styles.panel}>
        <header className={styles.panelHeader}>
          <h2>Конфигурация</h2>
          <span className={styles.muted}>
            v{config.version} · {config.environment}
          </span>
        </header>
        <dl className={styles.kv}>
          <dt>Адрес</dt>
          <dd>{config.public_url}</dd>
          <dt>Доступ</dt>
          <dd>
            {config.access_mode === 'allowlist' ? 'по списку' : 'открытый'} · админы {config.admins.join(', ') || '—'}
          </dd>
          <dt>Хранилище</dt>
          <dd>{config.storage_backend}</dd>
          <dt>Telegram-бот</dt>
          <dd>{config.telegram_bot_configured ? 'настроен' : 'не настроен'}</dd>
          <dt>AI</dt>
          <dd>{config.ai_enabled ? `${config.ai_base_url}` : 'выключен (нет AI_API_KEY)'}</dd>
          {config.ai_enabled
            ? Object.entries(config.ai_models).map(([key, value]) => [
                <dt key={`${key}-k`}>модель {key}</dt>,
                <dd key={`${key}-v`}>{String(value)}</dd>,
              ])
            : null}
        </dl>
        <div className={styles.chips}>
          {Object.entries(flags).map(([key, enabled]) => (
            <span key={key} className={enabled ? styles.chipOn : styles.chipOff}>
              {key}
            </span>
          ))}
        </div>
      </section>
      <section className={styles.panel}>
        <header className={styles.panelHeader}>
          <h2>Таблицы</h2>
          <span className={styles.muted}>
            соединения: {database.connections.map((c) => `${c.application || '?'}×${c.count}`).join(', ')}
          </span>
        </header>
        <table className={styles.table}>
          <tbody>
            {database.tables.map((table) => (
              <tr key={table.name}>
                <td>{table.name}</td>
                <td>{table.rows.toLocaleString('ru-RU')} строк</td>
                <td>{formatBytes(table.total_bytes)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}

export default function AdminPage() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const overview = useQuery({
    queryKey: OVERVIEW_KEY,
    queryFn: fetchAdminOverview,
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
    enabled: Boolean(user?.is_admin),
  })
  const storage = useMutation({
    mutationFn: refreshStorageUsage,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: OVERVIEW_KEY }),
  })

  if (user && !user.is_admin) return <Navigate to="/notes" replace />

  const refresh = () => void queryClient.invalidateQueries({ queryKey: OVERVIEW_KEY })
  const data = overview.data

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>Seyvix</p>
          <h1>Админка</h1>
        </div>
        <div className={styles.actions}>
          <span className={styles.muted}>
            {overview.isFetching ? 'обновление…' : `обновлено ${formatTime(overview.dataUpdatedAt / 1000)}`}
          </span>
          <button type="button" className={styles.button} onClick={() => storage.mutate()} disabled={storage.isPending}>
            Пересчитать файлы
          </button>
          <button type="button" className={styles.button} onClick={refresh}>
            Обновить
          </button>
        </div>
      </header>
      {overview.error ? <p className={styles.error}>{String(overview.error)}</p> : null}
      {!data ? <p className={styles.muted}>Загрузка…</p> : null}
      {data ? (
        <>
          <HostSection data={data} />
          <WorkersSection workers={data.workers} />
          <QueuesSection queues={data.queues} onChanged={refresh} />
          <ConfigSection data={data} />
        </>
      ) : null}
    </div>
  )
}
