import { useState } from 'react'
import { motion, useMotionValue, useTransform, useSpring } from 'framer-motion'
import CircularText from '../components/CircularText/CircularText'
import { useAuth } from '../contexts/AuthContext'
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
      {/* 3D тень под иконкой */}
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

export default function AuthPage() {
  const [loading, setLoading] = useState(false)
  const { mockLogin } = useAuth()

  function handleClick() {
    setLoading(true)
    if (import.meta.env.DEV) {
      mockLogin()
    } else {
      setTimeout(() => { window.location.href = '/api/v1/auth/telegram' }, 300)
    }
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
      </div>
    </div>
  )
}
