import { useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import styles from './FullscreenDialog.module.css'

/** Modal full-screen viewer; Escape / backdrop click closes, body scroll is locked while open. */
export function FullscreenDialog({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const onCloseRef = useRef(onClose)
  useEffect(() => {
    onCloseRef.current = onClose
  })

  useEffect(() => {
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCloseRef.current()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [])

  if (typeof document === 'undefined') return null

  return createPortal(
    <div className={styles.fullscreenBackdrop} role="dialog" aria-modal="true" aria-label={title} onClick={onClose}>
      <div className={styles.fullscreenShell} onClick={event => event.stopPropagation()}>
        <div className={styles.fullscreenChrome}>
          <strong>{title}</strong>
          <button type="button" onClick={onClose} title="Закрыть" autoFocus>
            <X size={16} />
          </button>
        </div>
        <div className={styles.fullscreenBody}>{children}</div>
      </div>
    </div>,
    document.body,
  )
}
