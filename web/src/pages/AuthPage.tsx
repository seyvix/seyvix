import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { motion, useMotionValue, useTransform, useSpring } from 'framer-motion'
import { Bot, ExternalLink, LoaderCircle, ShieldCheck, Sparkles } from 'lucide-react'
import { apiTelegramWebApp } from '../api/auth'
import CircularText from '../components/CircularText/CircularText'
import { useAuth } from '../contexts/AuthContext'
import {
  getTelegramWebApp,
  isTelegramMiniApp,
  prepareTelegramAuthSurface,
} from '../utils/telegramWebApp'
import styles from './AuthPage.module.css'

function TelegramLogo() {
  return (
    <img
      src="/telegramLogo.svg"
      alt="Telegram"
      className={styles.logo}
      draggable={false}
    />
  )
}

function TelegramIcon3D() {
  const mouseX = useMotionValue(0)
  const mouseY = useMotionValue(0)

  const rotateX = useSpring(useTransform(mouseY, [-0.5, 0.5], [18, -18]), { stiffness: 300, damping: 30 })
  const rotateY = useSpring(useTransform(mouseX, [-0.5, 0.5], [-18, 18]), { stiffness: 300, damping: 30 })

  function handleMouseMove(e: React.MouseEvent<HTMLDivElement>) {
    const rect = e.currentTarget.getBoundingClientRect()
    mouseX.set((e.clientX - rect.left) / rect.width - 0.5)
    mouseY.set((e.clientY - rect.top) / rect.height - 0.5)
  }

  function handleMouseLeave() {
    mouseX.set(0)
    mouseY.set(0)
  }

  return (
    <motion.div
      className={styles.iconWrapper}
      style={{ rotateX, rotateY, transformStyle: 'preserve-3d' }}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      whileTap={{ scale: 0.93 }}
      whileHover={{ scale: 1.06 }}
      transition={{ type: 'spring', stiffness: 300, damping: 20 }}
    >
      <TelegramLogo />
      <motion.div
        className={styles.iconShadow}
        style={{
          rotateX: useTransform(rotateX, v => -v * 0.5),
          rotateY: useTransform(rotateY, v => -v * 0.5),
        }}
      />
    </motion.div>
  )
}

const ERROR_MESSAGES: Record<string, string> = {
  invalid_telegram_login: 'Ошибка подтверждения Telegram. Попробуй ещё раз.',
  invalid_telegram_web_app_login: (
    'Telegram Mini App не подтвердил сессию. Открой приложение через бота ещё раз.'
  ),
  telegram_code_failed: 'Не удалось завершить вход. Попробуй ещё раз.',
  telegram_auth_not_configured: 'Telegram-авторизация не настроена.',
  telegram_web_app_failed: 'Не удалось войти внутри Telegram. Попробуй открыть вход заново.',
}

export default function AuthPage() {
  const navigate = useNavigate()
  const { loginWithTokens } = useAuth()
  const [searchParams] = useSearchParams()
  const webApp = useMemo(() => getTelegramWebApp(), [])
  const miniApp = isTelegramMiniApp(webApp)
  const errorCode = searchParams.get('error')
  const [loading, setLoading] = useState(miniApp && !errorCode)
  const [mode, setMode] = useState<'idle' | 'mini-app' | 'oauth' | 'dev'>(
    miniApp && !errorCode ? 'mini-app' : 'idle',
  )
  const miniAppLoginInFlightRef = useRef(false)
  const miniAppAutoAttemptedRef = useRef(false)

  const errorMessage = errorCode
    ? (ERROR_MESSAGES[errorCode] ?? 'Что-то пошло не так. Попробуй ещё раз.')
    : null

  const completeMiniAppLogin = useCallback(async () => {
    if (!webApp?.initData) return
    if (miniAppLoginInFlightRef.current) return
    miniAppLoginInFlightRef.current = true
    setLoading(true)
    setMode('mini-app')
    webApp.MainButton?.showProgress?.(true)
    try {
      const { user, access_token } = await apiTelegramWebApp(webApp.initData)
      webApp.HapticFeedback?.notificationOccurred?.('success')
      loginWithTokens(user, access_token)
      navigate('/notes', { replace: true })
    } catch (err) {
      console.error('[AuthPage] telegram web app login failed:', err)
      webApp.HapticFeedback?.notificationOccurred?.('error')
      navigate('/auth?error=telegram_web_app_failed', { replace: true })
    } finally {
      webApp.MainButton?.hideProgress?.()
      miniAppLoginInFlightRef.current = false
      setLoading(false)
    }
  }, [loginWithTokens, navigate, webApp])

  useEffect(() => {
    if (!webApp) return
    prepareTelegramAuthSurface(webApp)

    const mainButton = webApp.MainButton
    mainButton?.setText?.('Войти в Seyvix')
    mainButton?.onClick?.(completeMiniAppLogin)
    mainButton?.show()

    if (webApp.initData && !errorCode && !miniAppAutoAttemptedRef.current) {
      miniAppAutoAttemptedRef.current = true
      void completeMiniAppLogin()
    }

    return () => {
      mainButton?.offClick?.(completeMiniAppLogin)
      mainButton?.hide()
    }
  }, [completeMiniAppLogin, errorCode, webApp])

  function handleOAuthClick() {
    setLoading(true)
    setMode('oauth')
    webApp?.HapticFeedback?.impactOccurred?.('medium')
    window.location.href = '/api/v1/auth/telegram-login'
  }

  function handleDevClick() {
    setLoading(true)
    setMode('dev')
    window.location.href = '/api/v1/auth/telegram-dev-login'
  }

  const loadingText = mode === 'mini-app'
    ? 'подтверждаю mini app…'
    : mode === 'dev'
      ? 'локальный вход…'
      : 'переход в telegram…'
  const idleText = miniApp ? 'готово к входу внутри telegram' : 'без пароля и сторонних форм'

  return (
    <div className={styles.page}>
      <div className={styles.container}>
        <motion.div
          className={styles.copy}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: 'easeOut' }}
        >
          <div className={styles.eyebrow}>
            <ShieldCheck size={15} aria-hidden="true" />
            <span>{miniApp ? 'Telegram Mini App' : 'Telegram OAuth'}</span>
          </div>

          <h1>Seyvix</h1>
          <p>
            Вход через Telegram без пароля, чтобы сразу перейти к заметкам и сохранённым
            материалам.
          </p>
        </motion.div>

        <motion.button
          type="button"
          className={styles.ring}
          onClick={miniApp ? completeMiniAppLogin : handleOAuthClick}
          disabled={loading}
          aria-label="Войти через Telegram"
          initial={{ opacity: 0, scale: 0.94 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.4, delay: 0.08, ease: 'easeOut' }}
        >
          <CircularText
            text={miniApp ? 'TELEGRAM MINI APP • ' : 'АВТОРИЗОВАТЬСЯ В TELEGRAM • '}
            radius={118}
            fontSize={13}
            spinDuration={14}
            onHover="speedUp"
            className={styles.circularText}
          />
          <div className={styles.iconCenter}>
            {loading ? (
              <div className={styles.loadingMark}>
                <LoaderCircle size={32} aria-hidden="true" />
              </div>
            ) : (
              <TelegramIcon3D />
            )}
          </div>
        </motion.button>

        <div className={styles.actions}>
          {!miniApp && (
            <button
              type="button"
              className={styles.primaryButton}
              onClick={handleOAuthClick}
              disabled={loading}
            >
              <ExternalLink size={17} aria-hidden="true" />
              <span>Войти через Telegram</span>
            </button>
          )}

          {miniApp && (
            <button
              type="button"
              className={styles.primaryButton}
              onClick={completeMiniAppLogin}
              disabled={loading}
            >
              <Sparkles size={17} aria-hidden="true" />
              <span>Подтвердить вход</span>
            </button>
          )}

          {import.meta.env.DEV && !miniApp && (
            <button
              type="button"
              className={styles.secondaryButton}
              onClick={handleDevClick}
              disabled={loading}
            >
              <Bot size={17} aria-hidden="true" />
              <span>Локальный вход</span>
            </button>
          )}
        </div>

        <motion.p
          className={styles.subtitle}
          animate={{ opacity: loading ? 0.4 : 1 }}
        >
          {loading ? loadingText : idleText}
        </motion.p>

        {errorMessage && (
          <motion.p
            className={styles.error}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
          >
            {errorMessage}
          </motion.p>
        )}
      </div>
    </div>
  )
}
