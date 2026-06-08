import { useEffect, useState } from 'react'
import { NavLink } from 'react-router'
import { Tags, Trash2 } from 'lucide-react'
import { useLocalStorage } from '../../hooks/useLocalStorage'
import { useSettings } from '../../contexts/SettingsContext'
import { useAuth } from '../../contexts/AuthContext'
import styles from './AsideHeader.module.css'

const STORAGE_KEY = 'seyvix:sidebar-expanded'
const DESKTOP_COLUMN_OPTIONS = [1, 2, 3, 4, 5, 6, 7]
const MOBILE_COLUMN_OPTIONS = [1, 2, 3]
const MOBILE_COLUMNS_QUERY = '(max-width: 760px), (pointer: coarse)'

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

function IconSettings() {
  return (
    <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="8" cy="8" r="2.5"/>
      <path d="M8 1.5v1M8 13.5v1M1.5 8h1M13.5 8h1M3.4 3.4l.7.7M11.9 11.9l.7.7M3.4 12.6l.7-.7M11.9 4.1l.7-.7"/>
    </svg>
  )
}

function IconMore() {
  return (
    <svg width="18" height="18" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <circle cx="3.5" cy="8" r="1.3"/>
      <circle cx="8" cy="8" r="1.3"/>
      <circle cx="12.5" cy="8" r="1.3"/>
    </svg>
  )
}

function IconLogout() {
  return (
    <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6.5 13H3a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h3.5"/>
      <path d="M10 5l3 3-3 3"/>
      <path d="M13 8H6"/>
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
  const [isMobileColumns, setIsMobileColumns] = useState(false)
  const { cols, setCols } = useSettings()
  const { user, logout } = useAuth()

  const sidebarClass = [styles.sidebar, expanded ? styles.expanded : ''].filter(Boolean).join(' ')
  const columnOptions = isMobileColumns ? MOBILE_COLUMN_OPTIONS : DESKTOP_COLUMN_OPTIONS
  const activeCols = isMobileColumns ? Math.min(cols, 3) : cols
  const initials = user?.display_name
    ? user.display_name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase()
    : 'U'

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia === 'undefined') return
    const media = window.matchMedia(MOBILE_COLUMNS_QUERY)
    const handleChange = () => setIsMobileColumns(media.matches)

    handleChange()
    media.addEventListener?.('change', handleChange)
    return () => media.removeEventListener?.('change', handleChange)
  }, [])

  return (
    <aside className={sidebarClass}>
      <div className={styles.top}>
        <div className={styles.avatar}>
          <span className={styles.avatarInitials}>{initials}</span>
          {user?.telegram_photo_url && (
            <img
              className={styles.avatarImage}
              src={user.avatar_url ?? user.telegram_photo_url}
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
          onClick={() => setSettingsOpen(false)}
          className={({ isActive }) =>
            [styles.navItem, isActive ? styles.active : ''].filter(Boolean).join(' ')
          }
        >
          <span className={styles.navIcon}><IconNotes /></span>
          <span className={styles.navLabel}>Заметки</span>
          <span className={styles.navDot} />
        </NavLink>

        <NavLink
          to="/categories"
          onClick={() => setSettingsOpen(false)}
          className={({ isActive }) =>
            [styles.navItem, isActive ? styles.active : ''].filter(Boolean).join(' ')
          }
        >
          <span className={styles.navIcon}><Tags size={18} strokeWidth={1.8} /></span>
          <span className={styles.navLabel}>Категории</span>
          <span className={styles.navDot} />
        </NavLink>

        <NavLink
          to="/trash"
          onClick={() => setSettingsOpen(false)}
          className={({ isActive }) =>
            [styles.navItem, isActive ? styles.active : ''].filter(Boolean).join(' ')
          }
        >
          <span className={styles.navIcon}><Trash2 size={18} strokeWidth={1.8} /></span>
          <span className={styles.navLabel}>Корзина</span>
          <span className={styles.navDot} />
        </NavLink>
      </nav>

      <div className={styles.bottom}>
        <div className={[styles.moreMenu, settingsOpen ? styles.moreMenuOpen : ''].filter(Boolean).join(' ')}>
          <div className={styles.mobileProfileCard}>
            <div className={styles.avatar}>
              <span className={styles.avatarInitials}>{initials}</span>
              {user?.telegram_photo_url && (
                <img
                  className={styles.avatarImage}
                  src={user.avatar_url ?? user.telegram_photo_url}
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

          <NavLink to="/settings" className={styles.moreCard} onClick={() => setSettingsOpen(false)}>
            <span className={styles.moreCardIcon}><IconSettings /></span>
            <span className={styles.moreCardText}>Профиль и настройки</span>
          </NavLink>
          <div className={styles.columnsCard}>
            <div className={styles.settingsRow}>
              <span className={styles.settingsLabel}>Колонки</span>
              <div className={styles.colsPicker}>
                {columnOptions.map(n => (
                  <button
                    type="button"
                    key={n}
                    className={[styles.colsBtn, activeCols === n ? styles.colsBtnActive : ''].filter(Boolean).join(' ')}
                    onClick={() => setCols(n)}
                    aria-pressed={activeCols === n}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <button type="button" className={[styles.moreCard, styles.mobileLogoutCard].filter(Boolean).join(' ')} onClick={() => void logout()}>
            <span className={styles.moreCardIcon}><IconLogout /></span>
            <span className={styles.moreCardText}>Выйти</span>
          </button>
        </div>

        <button
          type="button"
          className={[styles.navItem, settingsOpen ? styles.active : ''].filter(Boolean).join(' ')}
          aria-expanded={settingsOpen}
          onClick={() => {
            if (!expanded) setExpanded(true)
            setSettingsOpen(v => !v)
          }}
        >
          <span className={styles.navIcon}><IconMore /></span>
          <span className={styles.navLabel}>Ещё</span>
        </button>

        <button type="button" className={[styles.navItem, styles.desktopLogout].filter(Boolean).join(' ')} onClick={() => void logout()}>
          <span className={styles.navIcon}><IconLogout /></span>
          <span className={styles.navLabel}>Выйти</span>
        </button>
      </div>

      <button
        type="button"
        className={styles.toggleBtn}
        onClick={() => {
          const next = !expanded
          setExpanded(next)
          if (!next) setSettingsOpen(false)
        }}
        aria-label={expanded ? 'Свернуть меню' : 'Развернуть меню'}
      >
        {expanded ? <IconChevronLeft /> : <IconChevronRight />}
      </button>
    </aside>
  )
}
