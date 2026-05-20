import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../contexts/AuthContext'
import { fetchAuthSessions, logoutAllSessions, revokeAuthSession } from '../api/account'
import {
  fetchSnapshotSettings,
  updateSnapshotSettings,
  type SnapshotFormatKey,
} from '../api/snapshots'
import { fetchTaxonomySettings, updateTaxonomySettings } from '../api/folders'
import { useSettings } from '../contexts/SettingsContext'
import styles from './SettingsPage.module.css'

type TabKey = 'profile' | 'snapshots' | 'taxonomy' | 'sessions'

const tabs: Array<{ key: TabKey; label: string; caption: string }> = [
  { key: 'profile', label: 'Профиль', caption: 'Аккаунт и внешний вид' },
  { key: 'snapshots', label: 'Снапшоты', caption: 'Форматы создания' },
  { key: 'taxonomy', label: 'Категории', caption: 'Профили и корзина' },
  { key: 'sessions', label: 'Сессии', caption: 'Устройства и входы' },
]

const snapshotLabels: Record<SnapshotFormatKey, string> = {
  screenshot: 'Скриншот',
  webpage_html: 'HTML-архив',
  pdf: 'PDF',
  markdown: 'Markdown',
  archive_org: 'Archive.org',
}

function formatDate(value: string | null): string {
  if (!value) return 'ещё не использовалась'
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function describeSession(userAgent: string | null): string {
  if (!userAgent) return 'Неизвестное устройство'
  if (userAgent.includes('Firefox')) return 'Firefox'
  if (userAgent.includes('Edg/')) return 'Microsoft Edge'
  if (userAgent.includes('Chrome')) return 'Chrome'
  if (userAgent.includes('Safari')) return 'Safari'
  if (userAgent === 'testclient') return 'Test client'
  return userAgent.slice(0, 72)
}

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('profile')
  const { user, logout } = useAuth()
  const { cols, setCols } = useSettings()
  const queryClient = useQueryClient()

  const snapshotSettings = useQuery({
    queryKey: ['snapshot-settings'],
    queryFn: fetchSnapshotSettings,
  })
  const sessions = useQuery({
    queryKey: ['auth-sessions'],
    queryFn: fetchAuthSessions,
  })
  const taxonomySettings = useQuery({
    queryKey: ['taxonomy-settings'],
    queryFn: fetchTaxonomySettings,
  })

  const updateSnapshots = useMutation({
    mutationFn: updateSnapshotSettings,
    onSuccess: (data) => {
      queryClient.setQueryData(['snapshot-settings'], data)
    },
  })
  const updateTaxonomy = useMutation({
    mutationFn: updateTaxonomySettings,
    onSuccess: (data) => {
      queryClient.setQueryData(['taxonomy-settings'], data)
    },
  })

  const revokeSession = useMutation({
    mutationFn: revokeAuthSession,
    onSuccess: async (_, sessionId) => {
      await queryClient.invalidateQueries({ queryKey: ['auth-sessions'] })
      const current = sessions.data?.find((session) => session.id === sessionId)
      if (current?.is_current) await logout()
    },
  })

  const logoutEverywhere = useMutation({
    mutationFn: logoutAllSessions,
    onSuccess: logout,
  })

  const initials = user?.display_name
    ? user.display_name.split(' ').map((word) => word[0]).join('').slice(0, 2).toUpperCase()
    : 'U'

  return (
    <section className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>Настройки</p>
          <h1>Аккаунт и обработка материалов</h1>
        </div>
      </header>

      <div className={styles.shell}>
        <nav className={styles.tabs} aria-label="Разделы настроек">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              className={[styles.tab, activeTab === tab.key ? styles.tabActive : ''].filter(Boolean).join(' ')}
              onClick={() => setActiveTab(tab.key)}
            >
              <span>{tab.label}</span>
              <small>{tab.caption}</small>
            </button>
          ))}
        </nav>

        <div className={styles.panel}>
          {activeTab === 'profile' && (
            <div className={styles.section}>
              <div className={styles.profileRow}>
                <div className={styles.avatar}>
                  <span>{initials}</span>
                  {(user?.avatar_url || user?.telegram_photo_url) && (
                    <img
                      src={user.avatar_url ?? user.telegram_photo_url ?? undefined}
                      alt=""
                      referrerPolicy="no-referrer"
                      onError={(event) => { event.currentTarget.hidden = true }}
                    />
                  )}
                </div>
                <div>
                  <h2>{user?.display_name ?? 'Пользователь'}</h2>
                  <p>{user?.telegram_username ? `@${user.telegram_username}` : 'Telegram аккаунт'}</p>
                </div>
              </div>

              <p className={styles.profileHint}>
                Профиль подтягивается из Telegram. Параметры отображения сохраняются локально на устройстве.
              </p>

              <div className={styles.settingBlock}>
                <div>
                  <h3>Колонки в сетке</h3>
                  <p>Настройка плотности ленты для широких экранов. На телефоне лента остаётся в один читаемый столбец.</p>
                </div>
                <div className={styles.segmented} aria-label="Количество колонок">
                  {[1, 2, 3, 4, 5, 6, 7].map((value) => (
                    <button
                      key={value}
                      className={cols === value ? styles.segmentActive : ''}
                      onClick={() => setCols(value)}
                      aria-pressed={cols === value}
                    >
                      {value}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {activeTab === 'snapshots' && (
            <div className={styles.section}>
              <div className={styles.sectionIntro}>
                <h2>Типы снапшотов</h2>
                <p>Выберите, какие представления сервер будет создавать для новых материалов.</p>
              </div>
              {snapshotSettings.isLoading && <p className={styles.muted}>Загружаю настройки...</p>}
              {snapshotSettings.isError && <p className={styles.error}>Не удалось загрузить настройки снапшотов.</p>}
              {snapshotSettings.data?.available.map((option) => {
                const key = option.key
                const override = snapshotSettings.data.overrides[key]
                const enabled = snapshotSettings.data.effective[key]
                return (
                  <div className={styles.toggleRow} key={key}>
                    <div>
                      <h3>{snapshotLabels[key] ?? option.label}</h3>
                      <p>{option.description}</p>
                      <small>
                        {override === null
                          ? `Наследуется от сервера: ${option.server_enabled ? 'включено' : 'выключено'}`
                          : 'Пользовательское значение'}
                      </small>
                    </div>
                    <div className={styles.toggleActions}>
                      <button
                        className={[styles.switch, enabled ? styles.switchOn : ''].filter(Boolean).join(' ')}
                        onClick={() => updateSnapshots.mutate({ [key]: !enabled })}
                        aria-pressed={enabled}
                      >
                        <span />
                      </button>
                      <button
                        className={styles.resetButton}
                        disabled={override === null}
                        onClick={() => updateSnapshots.mutate({ [key]: null })}
                      >
                        Сброс
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          {activeTab === 'sessions' && (
            <div className={styles.section}>
              <div className={styles.sectionIntro}>
                <h2>Активные сессии</h2>
                <p>История текущих входов, IP-адреса и возможность завершить отдельные устройства.</p>
              </div>
              <button
                className={styles.dangerButton}
                disabled={logoutEverywhere.isPending}
                onClick={() => logoutEverywhere.mutate()}
              >
                Выйти на всех устройствах
              </button>
              {sessions.isLoading && <p className={styles.muted}>Загружаю сессии...</p>}
              {sessions.isError && <p className={styles.error}>Не удалось загрузить активные сессии.</p>}
              <div className={styles.sessionList}>
                {sessions.data?.map((session) => (
                  <article className={styles.session} key={session.id}>
                    <div>
                      <h3>
                        {describeSession(session.user_agent)}
                        {session.is_current && <span>Текущая</span>}
                      </h3>
                      <p>IP: {session.ip_address ?? 'не определён'}</p>
                      <small>
                        Вход: {formatDate(session.created_at)} · Последняя активность: {formatDate(session.last_used_at)}
                      </small>
                    </div>
                    <button
                      className={styles.resetButton}
                      disabled={revokeSession.isPending}
                      onClick={() => revokeSession.mutate(session.id)}
                    >
                      Завершить
                    </button>
                  </article>
                ))}
              </div>
            </div>
          )}

          {activeTab === 'taxonomy' && (
            <div className={styles.section}>
              <div className={styles.sectionIntro}>
                <h2>Категории</h2>
                <p>Настройки профилей категорий, удаления материалов и срока хранения корзины.</p>
              </div>
              {taxonomySettings.isLoading && <p className={styles.muted}>Загружаю настройки категорий...</p>}
              {taxonomySettings.isError && <p className={styles.error}>Не удалось загрузить настройки категорий.</p>}
              {taxonomySettings.data && (
                <>
                  <div className={styles.toggleRow}>
                    <div>
                      <h3>Редактирование LLM-профилей</h3>
                      <p>Показывает форму ручного редактирования summary, keywords и examples.</p>
                    </div>
                    <button
                      className={[styles.switch, taxonomySettings.data.categoryProfileEditingEnabled ? styles.switchOn : ''].filter(Boolean).join(' ')}
                      disabled={updateTaxonomy.isPending}
                      onClick={() => updateTaxonomy.mutate({
                        categoryProfileEditingEnabled: !taxonomySettings.data.categoryProfileEditingEnabled,
                      })}
                      aria-pressed={taxonomySettings.data.categoryProfileEditingEnabled}
                    >
                      <span />
                    </button>
                  </div>

                  <div className={styles.toggleRow}>
                    <div>
                      <h3>Корзина</h3>
                      <p>Удалённые заметки сохраняются перед окончательной очисткой.</p>
                    </div>
                    <button
                      className={[styles.switch, taxonomySettings.data.trashEnabled ? styles.switchOn : ''].filter(Boolean).join(' ')}
                      disabled={updateTaxonomy.isPending}
                      onClick={() => updateTaxonomy.mutate({ trashEnabled: !taxonomySettings.data.trashEnabled })}
                      aria-pressed={taxonomySettings.data.trashEnabled}
                    >
                      <span />
                    </button>
                  </div>

                  <div className={styles.toggleRow}>
                    <div>
                      <h3>Срок хранения</h3>
                      <p>Дней до окончательной очистки удалённых заметок.</p>
                    </div>
                    <input
                      className={styles.numberInput}
                      type="number"
                      min={1}
                      max={365}
                      value={taxonomySettings.data.trashRetentionDays}
                      disabled={updateTaxonomy.isPending}
                      onChange={(event) => updateTaxonomy.mutate({
                        trashRetentionDays: Number(event.target.value),
                      })}
                    />
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
