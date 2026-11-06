import { AlertTriangle, X } from 'lucide-react'
import { useUploadContext } from '../../contexts/UploadContext'
import styles from './UploadToast.module.css'

/** Upload warnings/errors. Upload progress itself is shown on the optimistic note card. */
export function UploadToast() {
  const { notices, dismissNotice } = useUploadContext()
  if (notices.length === 0) return null

  return (
    <div className={styles.container} role="status" aria-live="polite">
      {notices.map(notice => (
        <div key={notice.id} className={styles.notice}>
          <AlertTriangle size={13} className={styles.iconWarn} aria-hidden />
          <span className={styles.noticeText}>{notice.message}</span>
          <button
            type="button"
            className={styles.noticeClose}
            aria-label="Закрыть"
            onClick={() => dismissNotice(notice.id)}
          >
            <X size={12} />
          </button>
        </div>
      ))}
    </div>
  )
}
