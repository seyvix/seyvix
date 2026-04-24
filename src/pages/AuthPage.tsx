import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { AuthApiError } from '../api/auth'
import styles from './AuthPage.module.css'

const ERROR_MESSAGES: Record<string, string> = {
  invalid_credentials:     'Неверный email или пароль.',
  email_already_registered: 'Этот email уже зарегистрирован.',
  validation_error:         'Проверьте правильность заполнения полей.',
}

function errorMessage(err: unknown): string {
  if (err instanceof AuthApiError) {
    return ERROR_MESSAGES[err.code] ?? err.message
  }
  return 'Что-то пошло не так. Попробуйте ещё раз.'
}

export default function AuthPage() {
  const [mode, setMode] = useState<'login' | 'register'>('login')

  const [email,       setEmail]       = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password,    setPassword]    = useState('')

  const [error,   setError]   = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const { login, register } = useAuth()
  const navigate = useNavigate()

  function switchMode(m: 'login' | 'register') {
    setMode(m)
    setError(null)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      if (mode === 'login') {
        await login(email, password)
      } else {
        await register(email, displayName, password)
      }
      navigate('/notes', { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <div className={styles.logo}>
          <div className={styles.logoIcon}>S</div>
          <span className={styles.logoText}>Seyvix</span>
        </div>

        <div className={styles.tabs}>
          <button
            className={[styles.tab, mode === 'login'    ? styles.tabActive : ''].join(' ')}
            onClick={() => switchMode('login')}
          >
            Войти
          </button>
          <button
            className={[styles.tab, mode === 'register' ? styles.tabActive : ''].join(' ')}
            onClick={() => switchMode('register')}
          >
            Регистрация
          </button>
        </div>

        <form className={styles.form} onSubmit={handleSubmit} noValidate>
          <div className={styles.field}>
            <label className={styles.label}>Email</label>
            <input
              className={[styles.input, error ? styles.inputError : ''].join(' ')}
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              autoComplete="email"
              autoFocus
            />
          </div>

          {mode === 'register' && (
            <div className={styles.field}>
              <label className={styles.label}>Имя</label>
              <input
                className={styles.input}
                type="text"
                placeholder="Как вас зовут?"
                value={displayName}
                onChange={e => setDisplayName(e.target.value)}
                required
                autoComplete="name"
              />
            </div>
          )}

          <div className={styles.field}>
            <label className={styles.label}>Пароль</label>
            <input
              className={[styles.input, error ? styles.inputError : ''].join(' ')}
              type="password"
              placeholder={mode === 'register' ? 'Минимум 8 символов' : ''}
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />
          </div>

          {error && <div className={styles.errorBox}>{error}</div>}

          <button className={styles.submitBtn} type="submit" disabled={loading}>
            {loading
              ? 'Загрузка…'
              : mode === 'login' ? 'Войти' : 'Создать аккаунт'
            }
          </button>
        </form>
      </div>
    </div>
  )
}
