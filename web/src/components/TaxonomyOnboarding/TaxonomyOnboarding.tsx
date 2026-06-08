import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check } from 'lucide-react'
import {
  fetchTaxonomyInterestOptions,
  fetchTaxonomyTree,
  initializeTaxonomyFromInterests,
} from '../../api/taxonomy'
import { LoaderSpinner } from '../LoaderSpinner'
import styles from './TaxonomyOnboarding.module.css'

export function TaxonomyOnboarding() {
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<string[]>(['software', 'ai'])
  const [customDescription, setCustomDescription] = useState('')

  const tree = useQuery({
    queryKey: ['taxonomy-tree'],
    queryFn: fetchTaxonomyTree,
  })
  const options = useQuery({
    queryKey: ['taxonomy-interest-options'],
    queryFn: fetchTaxonomyInterestOptions,
    enabled: tree.data?.length === 0,
  })

  const initialize = useMutation({
    mutationFn: initializeTaxonomyFromInterests,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['taxonomy-tree'] }),
        queryClient.invalidateQueries({ queryKey: ['folders'] }),
        queryClient.invalidateQueries({ queryKey: ['notes'] }),
      ])
    },
  })

  const shouldShow = tree.isSuccess && tree.data.length === 0
  const canSubmit = selected.length > 0 || customDescription.trim().length > 0
  const selectedSet = useMemo(() => new Set(selected), [selected])

  if (!shouldShow) return null

  function toggleInterest(slug: string) {
    setSelected(current =>
      current.includes(slug)
        ? current.filter(item => item !== slug)
        : [...current, slug],
    )
  }

  function submit() {
    if (!canSubmit || initialize.isPending) return
    initialize.mutate({
      interestSlugs: selected,
      customDescription,
    })
  }

  return (
    <div className={styles.backdrop} role="presentation">
      <section className={styles.panel} role="dialog" aria-modal="true" aria-labelledby="taxonomy-onboarding-title">
        <div className={styles.header}>
          <p className={styles.kicker}>Первичная настройка</p>
          <h1 id="taxonomy-onboarding-title">Что вам интересно?</h1>
          <p>
            Выберите направления или опишите свои увлечения свободно. На основе этого появится
            стартовая иерархия для автоназначения категорий.
          </p>
        </div>

        <div className={styles.options}>
          {(options.data ?? []).map(option => {
            const active = selectedSet.has(option.slug)
            return (
              <button
                key={option.slug}
                type="button"
                className={active ? styles.optionActive : styles.option}
                onClick={() => toggleInterest(option.slug)}
                aria-pressed={active}
              >
                <span className={styles.optionCheck} aria-hidden="true">
                  {active && <Check size={14} strokeWidth={2.5} />}
                </span>
                <span>
                  <strong>{option.name}</strong>
                  <small>{option.description}</small>
                </span>
              </button>
            )
          })}
        </div>

        <label className={styles.textareaLabel} htmlFor="taxonomy-custom-interests">
          <span>Свободное описание</span>
          <textarea
            id="taxonomy-custom-interests"
            value={customDescription}
            onChange={event => setCustomDescription(event.target.value)}
            placeholder="Например: изучаю робототехнику, компьютерное зрение, заметки по стартапам и семейные путешествия"
            rows={5}
          />
        </label>

        {initialize.isError && (
          <p className={styles.error}>Не удалось создать категории. Проверьте описание и попробуйте ещё раз.</p>
        )}

        <div className={styles.actions}>
          <button
            type="button"
            className={styles.primary}
            onClick={submit}
            disabled={!canSubmit || initialize.isPending}
          >
            {initialize.isPending ? <LoaderSpinner size="xs" className={styles.spinner} /> : <Check size={16} />}
            Создать категории
          </button>
        </div>
      </section>
    </div>
  )
}
