import type { CategoryProfileForm } from './categoryModel'
import styles from './Categories.module.css'

const FIELDS: Array<{ key: keyof CategoryProfileForm; label: string; placeholder: string }> = [
  { key: 'summary', label: 'Summary', placeholder: 'Что должно попадать в эту категорию и где её границы.' },
  { key: 'keywords', label: 'Keywords', placeholder: 'По одному на строку или через запятую' },
  { key: 'positiveExamples', label: 'Positive examples', placeholder: 'Что точно подходит' },
  { key: 'negativeExamples', label: 'Negative examples', placeholder: 'Что не должно попадать' },
]

/** The four LLM-profile textareas; `create` layout (grid) or `sidebar` layout (stacked). */
export function ProfileFormFields({
  form,
  onChange,
  variant,
}: {
  form: CategoryProfileForm
  onChange: (form: CategoryProfileForm) => void
  variant: 'create' | 'sidebar'
}) {
  return (
    <div className={variant === 'create' ? styles.createProfileGrid : styles.profileForm}>
      {FIELDS.map(field => (
        <label key={field.key} className={variant === 'create' && field.key === 'summary' ? styles.createProfileSummary : undefined}>
          <span>{field.label}</span>
          <textarea
            value={form[field.key]}
            onChange={event => onChange({ ...form, [field.key]: event.target.value })}
            placeholder={variant === 'create' ? field.placeholder : undefined}
          />
        </label>
      ))}
    </div>
  )
}
