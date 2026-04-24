import { AnimatePresence, motion } from 'framer-motion'
import { CheckCircle, Loader } from 'lucide-react'
import { useUploadContext } from '../../contexts/UploadContext'
import { useUploadJob } from '../../hooks/useUploadJob'
import styles from './UploadToast.module.css'

function JobRow({ jobId }: { jobId: string }) {
  const { data } = useUploadJob(jobId)

  if (!data) return null

  return (
    <div className={styles.job}>
      <div className={styles.jobHeader}>
        {data.status === 'done'
          ? <CheckCircle size={13} className={styles.iconDone} />
          : <Loader size={13} className={styles.iconSpinner} />
        }
        <span className={styles.jobTitle}>
          {data.status === 'done' ? 'Загружено' : 'Загрузка…'}
        </span>
        <span className={styles.jobCount}>{data.files.length} файл{data.files.length > 1 ? 'а' : ''}</span>
      </div>
      <div className={styles.fileList}>
        {data.files.map(f => (
          <div key={f.name} className={styles.fileRow}>
            <span className={styles.fileName}>{f.name}</span>
            <div className={styles.progressTrack}>
              <div
                className={`${styles.progressBar} ${f.status === 'processing' ? styles.progressBarActive : ''} ${f.status === 'done' ? styles.progressBarDone : ''}`}
                style={{ width: `${f.progress}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export function UploadToast() {
  const { jobs } = useUploadContext()

  return (
    <div className={styles.container}>
      <AnimatePresence>
        {jobs.map(({ jobId }) => (
          <motion.div
            key={jobId}
            initial={{ opacity: 0, y: 16, scale: 0.95 }}
            animate={{ opacity: 1, y: 0,  scale: 1    }}
            exit={{    opacity: 0, y: 8,  scale: 0.95, transition: { duration: 0.2 } }}
            transition={{ duration: 0.2 }}
          >
            <JobRow jobId={jobId} />
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  )
}
