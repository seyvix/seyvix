import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { Check, Sparkles } from 'lucide-react'
import {
  createCategory,
  fetchTaxonomySettings,
  suggestCategoryProfile,
  updateCategoryProfile,
  updateTaxonomySettings,
} from '../../api/folders'
import { useAiEnabled } from '../../hooks/useSearchCapabilities'
import type { Folder } from '../../types'
import {
  categoryUrl,
  EMPTY_PROFILE_FORM,
  formToProfile,
  hasProfileFormContent,
  profileFromDraft,
  type CategoryProfileForm,
} from './categoryModel'
import { ProfileFormFields } from './ProfileFormFields'
import styles from './Categories.module.css'

type ProfileMode = 'manual' | 'ai'

export const TAXONOMY_SETTINGS_QUERY_KEY = ['taxonomy-settings'] as const

/** Creates a root or child category, optionally with a manual or AI-drafted LLM profile. */
export function CategoryCreatePanel({
  parent,
  title,
  onCreated,
}: {
  parent: Folder | null
  title: string
  /** Called after creation with a warning when only the profile step failed. */
  onCreated: (profileWarning: string | null) => void
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const aiEnabled = useAiEnabled()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [requestedMode, setProfileMode] = useState<ProfileMode>('manual')
  const [profileForm, setProfileForm] = useState<CategoryProfileForm>(EMPTY_PROFILE_FORM)
  const [aiGuidance, setAiGuidance] = useState('')
  const profileMode: ProfileMode = aiEnabled ? requestedMode : 'manual'
  const settings = useQuery({ queryKey: TAXONOMY_SETTINGS_QUERY_KEY, queryFn: fetchTaxonomySettings })
  const profileEditingEnabled = settings.data?.categoryProfileEditingEnabled === true

  const create = useMutation({
    mutationFn: async () => {
      const category = await createCategory({ name, parentId: parent?.id ?? null, description })
      const wantsProfile = profileMode === 'ai' || hasProfileFormContent(profileForm)
      if (!wantsProfile) return { category, profileWarning: null }
      try {
        if (!profileEditingEnabled) {
          queryClient.setQueryData(TAXONOMY_SETTINGS_QUERY_KEY, await updateTaxonomySettings({ categoryProfileEditingEnabled: true }))
        }
        if (profileMode === 'ai') {
          const draft = await suggestCategoryProfile(category.id, aiGuidance.trim() || description.trim() || name.trim())
          await updateCategoryProfile(category.id, profileFromDraft(draft))
        } else {
          await updateCategoryProfile(category.id, formToProfile(profileForm))
        }
        return { category, profileWarning: null }
      } catch (error) {
        const reason = error instanceof Error ? ` ${error.message}` : ''
        return {
          category,
          profileWarning: profileMode === 'ai'
            ? `Категория создана, но ИИ-профиль не удалось заполнить.${reason}`
            : `Категория создана, но профиль не удалось сохранить.${reason}`,
        }
      }
    },
    onSuccess: ({ category, profileWarning }) => {
      queryClient.invalidateQueries({ queryKey: ['folders'] })
      queryClient.invalidateQueries({ queryKey: ['category-profile', category.id] })
      onCreated(profileWarning)
      navigate(categoryUrl(category.path))
    },
  })

  const canSubmit = Boolean(name.trim()) && !create.isPending

  return (
    <div className={styles.createPanel}>
      <div className={styles.createPanelHeader}>
        <div>
          <strong>{title}</strong>
          <span>{profileEditingEnabled ? 'Можно сразу задать LLM-профиль.' : 'Профили будут включены при создании с ручным или ИИ-заполнением.'}</span>
        </div>
        {aiEnabled && (
          <div className={styles.segmentedControl} aria-label="Способ заполнения профиля">
            <button type="button" className={profileMode === 'manual' ? styles.segmentActive : ''} onClick={() => setProfileMode('manual')}>
              Вручную
            </button>
            <button type="button" className={profileMode === 'ai' ? styles.segmentActive : ''} onClick={() => setProfileMode('ai')}>
              <Sparkles size={13} strokeWidth={1.8} />
              ИИ
            </button>
          </div>
        )}
      </div>

      <div className={styles.createBaseGrid}>
        <label>
          <span>Название</span>
          <input value={name} onChange={event => setName(event.target.value)} placeholder="Например: ML-инференс" />
        </label>
        <label>
          <span>Короткое описание</span>
          <input value={description} onChange={event => setDescription(event.target.value)} placeholder="Для дерева и контекста" />
        </label>
      </div>

      {profileMode === 'manual' ? (
        <ProfileFormFields form={profileForm} onChange={setProfileForm} variant="create" />
      ) : (
        <label className={styles.aiCreateBox}>
          <span>Инструкция для ИИ</span>
          <textarea
            value={aiGuidance}
            onChange={event => setAiGuidance(event.target.value)}
            placeholder="Опишите назначение категории, похожие материалы и что нужно отсекать. После создания профиль будет заполнен ИИ."
          />
        </label>
      )}

      <div className={styles.createActions}>
        <button type="button" className={styles.primaryAction} disabled={!canSubmit} onClick={() => create.mutate()}>
          {profileMode === 'ai' ? <Sparkles size={15} strokeWidth={1.8} /> : <Check size={15} strokeWidth={1.8} />}
          {create.isPending ? 'Создаю...' : profileMode === 'ai' ? 'Создать с ИИ' : 'Создать'}
        </button>
      </div>
      {create.isError && <div className={styles.stateError}>Не удалось создать категорию: {create.error.message}</div>}
    </div>
  )
}
