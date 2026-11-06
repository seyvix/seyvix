import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ACCESS_QUERY_KEY,
  createAccessGrant,
  deleteAccessGrant,
  fetchAccessOverview,
  parseAccessTarget,
  type AccessGrant,
} from '../../api/account'
import { ApiError } from '../../lib/apiError'
import styles from '../../pages/SettingsPage.module.css'

function formatDateTime(value: string | null): string {
  if (!value) return 'ещё не входил'
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function grantTitle(grant: AccessGrant): string {
  if (grant.display_name) return grant.display_name
  if (grant.username) return `@${grant.username}`
  return `ID ${grant.telegram_user_id}`
}

function errorText(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.status === 409) return 'Этот пользователь уже в списке доступа.'
  return error instanceof Error ? error.message : fallback
}

function GrantRow({ grant }: { grant: AccessGrant }) {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const revoke = useMutation({
    mutationFn: () => deleteAccessGrant(grant.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ACCESS_QUERY_KEY }),
  })

  return (
    <article className={styles.session}>
      <div>
        <h3>{grantTitle(grant)}</h3>
        <div className={styles.accessMeta}>
          {grant.telegram_user_id !== null && <span>ID {grant.telegram_user_id}</span>}
          {grant.username && grant.display_name && <span>@{grant.username}</span>}
          {grant.telegram_user_id === null && <span className={styles.badge}>ожидает первого входа</span>}
        </div>
        {grant.note && <p>{grant.note}</p>}
        <small>
          Добавлен: {formatDateTime(grant.created_at)} · Последний вход: {formatDateTime(grant.last_login_at)}
        </small>
        {revoke.isError && <p className={styles.error}>{errorText(revoke.error, 'Не удалось отозвать доступ.')}</p>}
      </div>
      {confirming ? (
        <div className={styles.confirmActions}>
          <button
            type="button"
            className={styles.dangerButton}
            disabled={revoke.isPending}
            onClick={() => revoke.mutate()}
          >
            Отозвать
          </button>
          <button type="button" className={styles.resetButton} onClick={() => setConfirming(false)}>
            Отмена
          </button>
        </div>
      ) : (
        <button type="button" className={styles.resetButton} onClick={() => setConfirming(true)}>
          Убрать
        </button>
      )}
    </article>
  )
}

/** Admin-only allowlist management (`/api/v1/admin/access`). */
export function AccessSettings() {
  const queryClient = useQueryClient()
  const [target, setTarget] = useState('')
  const [note, setNote] = useState('')
  const [touched, setTouched] = useState(false)
  const overview = useQuery({ queryKey: ACCESS_QUERY_KEY, queryFn: fetchAccessOverview })
  const parsedTarget = parseAccessTarget(target)

  const grant = useMutation({
    mutationFn: createAccessGrant,
    onSuccess: () => {
      setTarget('')
      setNote('')
      setTouched(false)
      return queryClient.invalidateQueries({ queryKey: ACCESS_QUERY_KEY })
    },
  })

  function submit(event: React.FormEvent) {
    event.preventDefault()
    setTouched(true)
    if (!parsedTarget || grant.isPending) return
    grant.mutate({ ...parsedTarget, ...(note.trim() ? { note: note.trim() } : {}) })
  }

  const invalid = touched && target.trim() !== '' && !parsedTarget

  return (
    <div className={styles.section}>
      <div className={styles.sectionIntro}>
        <h2>Доступ</h2>
        <p>
          Кто может входить в Seyvix. Добавь Telegram ID (пользователь видит его на экране входа)
          или @username — доступ привяжется к аккаунту при первом входе. Отзыв доступа сразу
          завершает все сессии пользователя.
        </p>
      </div>

      {overview.data?.mode === 'open' && (
        <p className={styles.muted}>
          Сейчас включён открытый режим (ACCESS_MODE=open): войти может любой пользователь Telegram.
          Список применяется только в режиме allowlist.
        </p>
      )}

      <form className={styles.accessForm} onSubmit={submit} noValidate>
        <input
          className={styles.textInput}
          value={target}
          onChange={event => setTarget(event.target.value)}
          onBlur={() => setTouched(true)}
          placeholder="Telegram ID или @username"
          aria-label="Telegram ID или @username"
          aria-invalid={invalid}
          autoComplete="off"
        />
        <input
          className={styles.textInput}
          value={note}
          onChange={event => setNote(event.target.value)}
          placeholder="Заметка (необязательно)"
          aria-label="Заметка"
          maxLength={200}
        />
        <button type="submit" className={styles.primaryButton} disabled={grant.isPending || !parsedTarget}>
          Выдать доступ
        </button>
      </form>
      {invalid && <p className={styles.error}>Введи числовой Telegram ID или username (5–32 символа).</p>}
      {grant.isError && <p className={styles.error}>{errorText(grant.error, 'Не удалось выдать доступ.')}</p>}

      {overview.isLoading && <p className={styles.muted}>Загружаю список доступа...</p>}
      {overview.isError && <p className={styles.error}>{errorText(overview.error, 'Не удалось загрузить список доступа.')}</p>}

      {overview.data && (
        <div className={styles.sessionList}>
          {overview.data.admins.length > 0 && (
            <p className={styles.muted}>
              Администраторы (ADMIN_TELEGRAM_IDS): {overview.data.admins.join(', ')}
            </p>
          )}
          {overview.data.items.length === 0
            ? <p className={styles.muted}>Пока никому, кроме администраторов, доступ не выдан.</p>
            : overview.data.items.map(item => <GrantRow key={item.id} grant={item} />)}
        </div>
      )}
    </div>
  )
}
