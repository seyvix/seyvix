import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, CheckCircle, Loader, X } from 'lucide-react'
import { useUploadContext, type UploadJobEntry } from '../../contexts/UploadContext'
import { useUploadJob } from '../../hooks/useUploadJob'
import styles from './UploadToast.module.css'

function JobRow({ job }: { job: UploadJobEntry }) {
  const { data } = useUploadJob(job.jobId)

  if (!data) return null

  const isDone = data.status === 'done'

  return (
    <div className={styles.job}>
      <div className={styles.jobHeader}>
        {isDone
          ? <CheckCircle size={13} className={styles.iconDone} />
          : <Loader size={13} className={styles.iconSpinner} />
        }
        <span className={styles.jobTitle}>
          {isDone ? 'Готово' : 'Загрузка…'}
        </span>
        {job.label && (
          <span className={styles.jobCount}>{job.label}</span>
        )}
      </div>
    </div>
  )
}

export function UploadToast() {
  const { jobs, notices, dismissNotice } = useUploadContext()

  return (
    <div className={styles.container}>
      <AnimatePresence>
        {notices.map(notice => (
          <motion.div
            key={notice.id}
            initial={{ opacity: 0, y: 16, scale: 0.95 }}
            animate={{ opacity: 1, y: 0,  scale: 1    }}
            exit={{    opacity: 0, y: 8,  scale: 0.95, transition: { duration: 0.2 } }}
            transition={{ duration: 0.2 }}
          >
            <div className={`${styles.job} ${styles.notice}`}>
              <div className={styles.jobHeader}>
                <AlertTriangle size={13} className={styles.iconWarn} />
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
            </div>
          </motion.div>
        ))}
        {jobs.map((job) => (
          <motion.div
            key={job.jobId}
            initial={{ opacity: 0, y: 16, scale: 0.95 }}
            animate={{ opacity: 1, y: 0,  scale: 1    }}
            exit={{    opacity: 0, y: 8,  scale: 0.95, transition: { duration: 0.2 } }}
            transition={{ duration: 0.2 }}
          >
            <JobRow job={job} />
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  )
}
