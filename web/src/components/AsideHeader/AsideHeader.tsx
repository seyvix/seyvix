import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useLocalStorage } from '../../hooks/useLocalStorage'
import { useSettings } from '../../contexts/SettingsContext'
import { useAuth } from '../../contexts/AuthContext'
import styles from './AsideHeader.module.css'

const STORAGE_KEY = 'seyvix:sidebar-expanded'

function IconNotes() {
  return (
    <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="2" width="12" height="12" rx="2"/>
      <line x1="5" y1="6" x2="11" y2="6"/>
      <line x1="5" y1="9" x2="11" y2="9"/>
      <line x1="5" y1="12" x2="8" y2="12"/>
    </svg>
  )
}

function IconFolders() {
  return (
    <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 4a1 1 0 0 1 1-1h3.586a1 1 0 0 1 .707.293L8.414 4.5H13a1 1 0 0 1 1 1V12a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V4z"/>
    </svg>
  )
}

function IconSettings() {
  return (
    <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="8" cy="8" r="2.5"/>
      <path d="M8 1.5v1M8 13.5v1M1.5 8h1M13.5 8h1M3.4 3.4l.7.7M11.9 11.9l.7.7M3.4 12.6l.7-.7M11.9 4.1l.7-.7"/>
    </svg>
  )
}

function IconProfile() {
  return (
    <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="8" cy="5.5" r="2.5"/>
      <path d="M2.5 13.5c0-3 2.5-4.5 5.5-4.5s5.5 1.5 5.5 4.5"/>
    </svg>
  )
}

function IconChevronRight() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="4,2 8,6 4,10"/>
    </svg>
  )
}

function IconChevronLeft() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="8,2 4,6 8,10"/>
    </svg>
  )
}

export default function AsideHeader() {
  const [expanded, setExpanded] = useLocalStorage(STORAGE_KEY, false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const { cols, setCols } = useSettings()
  const { user } = useAuth()

  const sidebarClass = [styles.sidebar, expanded ? styles.expanded : ''].filter(Boolean).join(' ')
  const initials = user?.display_name
    ? user.display_name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase()
    : 'U'

  return (
    <aside className={sidebarClass}>
      <div className={styles.top}>
        <div className={styles.avatar}>
          <span className={styles.avatarInitials}>{initials}</span>
          {user?.telegram_photo_url && (
            <img
              className={styles.avatarImage}
              src={user.telegram_photo_url}
              alt=""
              referrerPolicy="no-referrer"
              onError={event => { event.currentTarget.hidden = true }}
            />
          )}
        </div>
        <div className={styles.userInfo}>
          <span className={styles.logoText}>{user?.display_name ?? 'Пользователь'}</span>
          {user?.telegram_username && (
            <span className={styles.username}>@{user.telegram_username}</span>
          )}
        </div>
      </div>

      <nav className={styles.nav}>
        <NavLink
          to="/notes"
          className={({ isActive }) =>
            [styles.navItem, isActive ? styles.active : ''].filter(Boolean).join(' ')
          }
        >
          <span className={styles.navIcon}><IconNotes /></span>
          <span className={styles.navLabel}>Заметки</span>
          <span className={styles.navDot} />
        </NavLink>

        <NavLink
          to="/folders"
          className={({ isActive }) =>
            [styles.navItem, isActive ? styles.active : ''].filter(Boolean).join(' ')
          }
        >
          <span className={styles.navIcon}><IconFolders /></span>
          <span className={styles.navLabel}>Папки</span>
          <span className={styles.navDot} />
        </NavLink>
      </nav>

      <div className={styles.bottom}>
        <button
          className={[styles.navItem, settingsOpen ? styles.active : ''].filter(Boolean).join(' ')}
          onClick={() => setSettingsOpen(v => !v)}
        >
          <span className={styles.navIcon}><IconSettings /></span>
          <span className={styles.navLabel}>Настройки</span>
        </button>

        {settingsOpen && (
          <div className={styles.settingsPanel}>
            <div className={styles.settingsRow}>
              <span className={styles.settingsLabel}>Колонки</span>
              <div className={styles.colsPicker}>
                {[3, 4, 5].map(n => (
                  <button
                    key={n}
                    className={[styles.colsBtn, cols === n ? styles.colsBtnActive : ''].filter(Boolean).join(' ')}
                    onClick={() => setCols(n)}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
        <button className={styles.navItem}>
          <span className={styles.navIcon}><IconProfile /></span>
          <span className={styles.navLabel}>Профиль</span>
        </button>
      </div>

      <button
        className={styles.toggleBtn}
        onClick={() => setExpanded(!expanded)}
        aria-label={expanded ? 'Свернуть меню' : 'Развернуть меню'}
      >
        {expanded ? <IconChevronLeft /> : <IconChevronRight />}
      </button>
    </aside>
  )
}
