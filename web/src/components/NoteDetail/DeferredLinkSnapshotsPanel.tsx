import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Check, X } from 'lucide-react'
import { decideDeferredLinkSnapshots } from '../../api/notes'
import { requestChangeFeedSync } from '../../hooks/useNotesChangeFeed'
import type { Note } from '../../types'
import styles from './Sidebar.module.css'

/** Asks whether to snapshot the remaining links of a long text (backend defers them). */
export function DeferredLinkSnapshotsPanel({ note }: { note: Note }) {
  const queryClient = useQueryClient()
  const decision = useMutation({
    mutationFn: (value: 'accept' | 'reject') => decideDeferredLinkSnapshots(note.slug, value),
    onSuccess: updated => {
      queryClient.setQueriesData<Note>({ queryKey: ['note'] }, old => (
        old && (old.id === updated.id || old.slug === updated.slug) ? updated : old
      ))
      queryClient.invalidateQueries({ queryKey: ['snapshot-jobs', note.id] })
      queryClient.invalidateQueries({ queryKey: ['snapshot-artifacts', note.id] })
      requestChangeFeedSync()
    },
  })

  const deferred = note.deferredLinkSnapshots
  if (!deferred) return null

  return (
    <section className={styles.deferredLinksPanel}>
      <div className={styles.deferredLinksHeader}>
        <AlertTriangle size={14} />
        <span>Ссылки в тексте</span>
      </div>
      <p>
        Обработано {deferred.processedLinks} ссылок из {deferred.totalLinks}. Сделать снапшоты
        остальных {deferred.remainingLinks}?
      </p>
      <div className={styles.deferredLinksActions}>
        <button
          type="button"
          className={styles.deferredLinksAccept}
          disabled={decision.isPending}
          onClick={() => decision.mutate('accept')}
        >
          <Check size={13} />
          Да
        </button>
        <button
          type="button"
          className={styles.deferredLinksReject}
          disabled={decision.isPending}
          onClick={() => decision.mutate('reject')}
        >
          <X size={13} />
          Нет
        </button>
      </div>
      {decision.isError && <span className={styles.deferredLinksError}>Не удалось сохранить выбор.</span>}
    </section>
  )
}
