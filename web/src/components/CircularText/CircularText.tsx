import { useEffect } from 'react'
import { motion, useAnimation, useMotionValue } from 'framer-motion'
import './CircularText.css'

interface CircularTextProps {
  text: string
  radius?: number
  fontSize?: number
  spinDuration?: number
  onHover?: 'speedUp' | 'slowDown' | 'pause' | 'goBonkers'
  className?: string
}

const getRotationTransition = (duration: number, from: number) => ({
  from,
  to: from + 360,
  ease: 'linear' as const,
  duration,
  type: 'tween' as const,
  repeat: Infinity,
})

export default function CircularText({
  text,
  radius = 88,
  fontSize = 11,
  spinDuration = 14,
  onHover = 'speedUp',
  className = '',
}: CircularTextProps) {
  const letters = Array.from(text)
  const controls = useAnimation()
  const rotation = useMotionValue(0)

  useEffect(() => {
    const start = rotation.get()
    controls.start({
      rotate: start + 360,
      transition: getRotationTransition(spinDuration, start),
    })
  }, [spinDuration, text])

  function handleHoverStart() {
    const start = rotation.get()
    const durationMap = {
      speedUp:   spinDuration / 4,
      slowDown:  spinDuration * 2,
      pause:     spinDuration,
      goBonkers: spinDuration / 20,
    }
    controls.start({
      rotate: start + 360,
      transition: getRotationTransition(durationMap[onHover] ?? spinDuration, start),
    })
  }

  function handleHoverEnd() {
    const start = rotation.get()
    controls.start({
      rotate: start + 360,
      transition: getRotationTransition(spinDuration, start),
    })
  }

  return (
    <motion.div
      className={`circular-text ${className}`}
      style={{ rotate: rotation, width: radius * 2, height: radius * 2 }}
      initial={{ rotate: 0 }}
      animate={controls}
      onMouseEnter={handleHoverStart}
      onMouseLeave={handleHoverEnd}
    >
      {letters.map((letter, i) => {
        const deg = (360 / letters.length) * i
        const transform = `rotateZ(${deg}deg) translateY(-${radius - fontSize * 1.2}px)`
        return (
          <span key={i} style={{ transform, fontSize }}>
            {letter}
          </span>
        )
      })}
    </motion.div>
  )
}
