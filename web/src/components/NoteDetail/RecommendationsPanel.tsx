import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { Sparkles } from 'lucide-react'
import { LoaderSpinner } from '../LoaderSpinner'
import { fetchNoteRecommendations } from '../../api/notes'
import type { Note } from '../../types'
import { recommendationScoreLabel, recommendedNoteTypeLabel } from './format'
import styles from './Sidebar.module.css'

/** "Similar materials" list (hybrid search on the backend; works without AI via FTS). */
export function RecommendationsPanel({ note }: { note: Note }) {
  const recommendations = useQuery({
    queryKey: ['note-recommendations', note.id],
    queryFn: ({ signal }) => fetchNoteRecommendations(note.slug, 5, signal),
    staleTime: 5 * 60_000,
  })
  const items = recommendations.data ?? []

  return (
    <section className={styles.recommendationsPanel}>
      <div className={styles.recommendationsHeader}>
        <Sparkles size={14} />
        <span>Похожие материалы</span>
        {recommendations.isFetching && !recommendations.isLoading && (
          <LoaderSpinner size="xs" className={styles.recommendationsSpinner} />
        )}
      </div>

      {recommendations.isLoading ? (
        <div className={styles.recommendationsState}><LoaderSpinner size="md" /></div>
      ) : recommendations.isError ? (
        <div className={styles.recommendationsState}>Не удалось загрузить рекомендации</div>
      ) : items.length === 0 ? (
        <div className={styles.recommendationsState}>Похожих материалов пока нет</div>
      ) : (
        <div className={styles.recommendationsList}>
          {items.map(item => {
            const scoreLabel = recommendationScoreLabel(item.score)
            return (
              <Link key={item.id} className={styles.recommendationItem} to={`/notes/${item.slug}`}>
                <div className={styles.recommendationTop}>
                  <strong>{item.title || 'Без названия'}</strong>
                  {scoreLabel && <span className={styles.recommendationScore}>{scoreLabel}</span>}
                </div>
                <div className={styles.recommendationMeta}>
                  <span>{recommendedNoteTypeLabel(item)}</span>
                  {item.tags.slice(0, 2).map(tag => <span key={tag.id}>#{tag.name}</span>)}
                </div>
                {item.matchedText && <p className={styles.recommendationText}>{item.matchedText}</p>}
              </Link>
            )
          })}
        </div>
      )}
    </section>
  )
}
