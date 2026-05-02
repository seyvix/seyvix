import { motion } from 'framer-motion'
import styles from './LoaderScreen.module.css'

interface LoaderScreenProps {
  subtitle?: string
}

const RINGS = [
  { size: 120, opacity: 0.6 },
  { size: 180, opacity: 0.4 },
  { size: 240, opacity: 0.25 },
]

export default function LoaderScreen({ subtitle }: LoaderScreenProps) {
  return (
    <motion.div
      className={styles.screen}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.2 }}
    >
      <div className={styles.grid} />
      <div className={styles.rings}>
        {RINGS.map((ring, i) => (
          <motion.div
            key={i}
            className={styles.ring}
            style={{
              width: ring.size,
              height: ring.size,
              borderColor: `rgba(99, 102, 241, ${ring.opacity})`,
            }}
            animate={{
              rotate: 360,
              scale: [1, 1.04 + i * 0.02, 1],
              opacity: [0.7, 1, 0.7],
            }}
            transition={{
              rotate: {
                duration: 5 + i * 3,
                repeat: Infinity,
                ease: 'linear',
              },
              scale: {
                duration: 2.5,
                repeat: Infinity,
                ease: 'easeInOut',
                delay: i * 0.3,
              },
              opacity: {
                duration: 2.5,
                repeat: Infinity,
                ease: 'easeInOut',
                delay: i * 0.3,
              },
            }}
          />
        ))}
      </div>
      {subtitle && (
        <motion.p
          className={styles.subtitle}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3, duration: 0.4 }}
        >
          {subtitle}
        </motion.p>
      )}
    </motion.div>
  )
}
