import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { motion, useMotionValue, useTransform, useSpring } from 'framer-motion'
import CircularText from '../components/CircularText/CircularText'
import styles from './AuthPage.module.css'
import { useAuth } from '../contexts/AuthContext'
import type { UserResponse } from '../api/auth'

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

function TelegramIcon3D({ onClick }: { onClick: () => void }) {
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
      onClick={onClick}
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
  telegram_code_failed: 'Не удалось завершить вход. Попробуй ещё раз.',
  telegram_auth_not_configured: 'Telegram-авторизация не настроена.',
}

export default function AuthPage() {
  const [loading, setLoading] = useState(false)
  const [searchParams] = useSearchParams()
  const { loginWithTokens } = useAuth()
  const listenerRef = useRef<((e: MessageEvent) => void) | null>(null)

  useEffect(() => {
    return () => {
      if (listenerRef.current) {
        window.removeEventListener('message', listenerRef.current)
      }
    }
  }, [])

  const errorCode = searchParams.get('error')
  const errorMessage = errorCode
    ? (ERROR_MESSAGES[errorCode] ?? 'Что-то пошло не так. Попробуй ещё раз.')
    : null

  function handleClick() {
    setLoading(true)

    const popup = window.open('/api/v1/auth/telegram-login', '_blank', 'width=600,height=700')
    if (!popup) {
      // fallback if popup blocked
      window.location.href = '/api/v1/auth/telegram-login'
      return
    }

    function onMessage(e: MessageEvent) {
      if (e.origin !== window.location.origin) return
      if (e.data?.type !== 'TELEGRAM_AUTH_SUCCESS') return
      window.removeEventListener('message', onMessage)
      listenerRef.current = null
      loginWithTokens(e.data.user as UserResponse, e.data.accessToken as string)
      // RequireGuest will redirect to /notes automatically
    }

    listenerRef.current = onMessage
    window.addEventListener('message', onMessage)
  }

  return (
    <div className={styles.page}>
      <div className={styles.container}>
        <div className={styles.ring} onClick={handleClick}>
          <CircularText
            text="АВТОРИЗОВАТЬСЯ В TELEGRAM • "
            radius={118}
            fontSize={13}
            spinDuration={14}
            onHover="speedUp"
            className={styles.circularText}
          />
          <div className={styles.iconCenter}>
            <TelegramIcon3D onClick={handleClick} />
          </div>
        </div>

        <motion.p
          className={styles.subtitle}
          animate={{ opacity: loading ? 0.4 : 1 }}
        >
          {loading ? 'переход в telegram…' : 'авторизоваться через telegram'}
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
