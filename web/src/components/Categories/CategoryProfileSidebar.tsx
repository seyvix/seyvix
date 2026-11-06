import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Edit3, Sparkles, X } from 'lucide-react'
import { fetchCategoryProfile, fetchTaxonomySettings, suggestCategoryProfile, updateCategoryProfile } from '../../api/folders'
import { useAiEnabled } from '../../hooks/useSearchCapabilities'
import type { CategoryProfileDraft, Folder } from '../../types'
import { formToProfile, profileFormFrom, type CategoryProfileForm } from './categoryModel'
import { TAXONOMY_SETTINGS_QUERY_KEY } from './CategoryCreatePanel'
import { ProfileFormFields } from './ProfileFormFields'
import styles from './Categories.module.css'

function ProfileList({ title, values }: { title: string; values: string[] }) {
  return (
    <div className={styles.profileList}>
      <span>{title}</span>
      {values.length ? (
        <div className={styles.profileChips}>
          {values.map(value => <small key={value}>{value}</small>)}
        </div>
      ) : (
        <p>Нет данных.</p>
      )}
    </div>
  )
}

function ProfileLists({ profile }: { profile: { keywords: string[]; positiveExamples: string[]; negativeExamples: string[] } }) {
  return (
    <div className={styles.profileLists}>
      <ProfileList title="Ключевые слова" values={profile.keywords} />
      <ProfileList title="Что подходит" values={profile.positiveExamples} />
      <ProfileList title="Что не подходит" values={profile.negativeExamples} />
    </div>
  )
}

/** Slide-over with the category's LLM classification profile (view, edit, AI-suggested draft). */
export function CategoryProfileSidebar({ category, onClose }: { category: Folder; onClose: () => void }) {
  const queryClient = useQueryClient()
  const aiEnabled = useAiEnabled()
  const profileKey = ['category-profile', category.id]
  const profile = useQuery({ queryKey: profileKey, queryFn: () => fetchCategoryProfile(category.id) })
  const settings = useQuery({ queryKey: TAXONOMY_SETTINGS_QUERY_KEY, queryFn: fetchTaxonomySettings })
  const editingAllowed = settings.data?.categoryProfileEditingEnabled === true

  const [editForm, setEditForm] = useState<CategoryProfileForm | null>(null)
  const [guidance, setGuidance] = useState('')
  const [draft, setDraft] = useState<CategoryProfileDraft | null>(null)
  const editing = editingAllowed ? editForm : null

  const save = useMutation({
    mutationFn: (form: CategoryProfileForm) => updateCategoryProfile(category.id, formToProfile(form)),
    onSuccess: saved => {
      setEditForm(null)
      setDraft(null)
      queryClient.setQueryData(profileKey, saved)
    },
  })
  const suggest = useMutation({
    mutationFn: () => suggestCategoryProfile(category.id, guidance),
    onSuccess: setDraft,
  })

  return (
    <>
      <button type="button" className={styles.profileScrim} aria-label="Закрыть профиль категории" onClick={onClose} />
      <aside className={styles.profileSidebar} aria-label="LLM-профиль категории">
        <div className={styles.profileSidebarHeader}>
          <div>
            <span>{editingAllowed ? 'редактирование включено' : 'только просмотр'}</span>
            <h3>LLM-профиль</h3>
          </div>
          <button type="button" className={styles.iconAction} onClick={onClose} aria-label="Закрыть профиль">
            <X size={17} strokeWidth={1.8} />
          </button>
        </div>

        {profile.isPending && <div className={styles.emptyBlock}>Загружаю профиль категории...</div>}
        {profile.isError && <div className={styles.stateError}>Не удалось загрузить профиль категории.</div>}
        {profile.data && (
          <div className={styles.profileBody}>
            {editing ? (
              <ProfileFormFields form={editing} onChange={setEditForm} variant="sidebar" />
            ) : (
              <>
                <p className={styles.profileSummary}>{profile.data.summary || 'Описание профиля пока не заполнено.'}</p>
                <ProfileLists profile={profile.data} />
              </>
            )}

            <div className={styles.profileActions}>
              {editingAllowed && !editing && (
                <button type="button" className={styles.secondaryAction} onClick={() => setEditForm(profileFormFrom(profile.data))}>
                  <Edit3 size={15} strokeWidth={1.8} />
                  Редактировать
                </button>
              )}
              {editing && (
                <>
                  <button type="button" className={styles.primaryAction} disabled={save.isPending} onClick={() => save.mutate(editing)}>
                    <Check size={15} strokeWidth={1.8} />
                    Сохранить
                  </button>
                  <button type="button" className={styles.secondaryAction} onClick={() => setEditForm(null)}>
                    <X size={15} strokeWidth={1.8} />
                    Отмена
                  </button>
                </>
              )}
            </div>
            {save.isError && <div className={styles.stateError}>Не удалось сохранить профиль категории.</div>}

            {editingAllowed && aiEnabled && (
              <>
                <div className={styles.profileSuggest}>
                  <textarea
                    value={guidance}
                    onChange={event => setGuidance(event.target.value)}
                    placeholder="Опишите, что должно попадать в эту категорию или её подкатегории."
                  />
                  <button
                    type="button"
                    className={styles.secondaryAction}
                    disabled={!guidance.trim() || suggest.isPending}
                    onClick={() => suggest.mutate()}
                  >
                    <Sparkles size={15} strokeWidth={1.8} />
                    {suggest.isPending ? 'Готовлю...' : 'Предложить улучшение'}
                  </button>
                </div>
                {suggest.isError && <div className={styles.stateError}>Не удалось получить черновик профиля: {suggest.error.message}</div>}

                {draft && (
                  <div className={styles.profileDraft}>
                    <div>
                      <strong>{draft.summary || 'Без summary'}</strong>
                      <p>{draft.reasoning}</p>
                    </div>
                    <ProfileLists profile={draft} />
                    <div className={styles.profileActions}>
                      <button type="button" className={styles.primaryAction} disabled={save.isPending} onClick={() => save.mutate(profileFormFrom(draft))}>
                        <Check size={15} strokeWidth={1.8} />
                        Принять
                      </button>
                      <button type="button" className={styles.secondaryAction} onClick={() => setDraft(null)}>
                        <X size={15} strokeWidth={1.8} />
                        Отклонить
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </aside>
    </>
  )
}
