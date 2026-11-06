import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, FolderTree, Plus, Search, Tag as TagIcon, X } from 'lucide-react'
import {
  acceptTagSuggestion,
  acceptTaxonomyAssignment,
  assignCategoryToContent,
  assignExistingTagToContent,
  createOrFindTag,
  createTaxonomyCategory,
  fetchContentTagJobs,
  fetchContentTags,
  fetchContentTagSuggestions,
  fetchTaxonomyAssignments,
  fetchTaxonomyClassificationJobs,
  rejectTagSuggestion,
  rejectTaxonomyAssignment,
  searchTaxonomyCategories,
} from '../../api/enrichment'
import { requestChangeFeedSync } from '../../hooks/useNotesChangeFeed'
import type { Note, TaxonomyCategory } from '../../types'
import { TagChips } from './DetailParts'
import { isActiveJob, JOB_PROGRESS_POLL_MS, jobStatusLabel } from './format'
import styles from './Sidebar.module.css'

function pollWhileActive(query: { state: { data?: Array<{ status: string }> } }): number | false {
  return query.state.data?.some(isActiveJob) ? JOB_PROGRESS_POLL_MS : false
}

function useEnrichmentRefresh(noteId: string) {
  const queryClient = useQueryClient()
  return () => {
    for (const key of ['content-tags', 'content-tag-suggestions', 'content-tag-jobs', 'taxonomy-assignments', 'taxonomy-classification-jobs']) {
      queryClient.invalidateQueries({ queryKey: [key, noteId] })
    }
    // Only the mounted note detail refetches; lists catch up through the change feed.
    queryClient.invalidateQueries({ queryKey: ['note'] })
    requestChangeFeedSync()
  }
}

function SuggestionRow({
  label,
  confidence,
  onAccept,
  onReject,
}: {
  label: string
  confidence: number | null
  onAccept: () => void
  onReject: () => void
}) {
  return (
    <div className={styles.suggestionItem}>
      <span>{label}</span>
      {confidence !== null && <b>{Math.round(confidence * 100)}%</b>}
      <button type="button" onClick={onAccept} title="Принять"><Check size={13} /></button>
      <button type="button" onClick={onReject} title="Отклонить"><X size={13} /></button>
    </div>
  )
}

function JobList({ jobs, label }: { jobs: Array<{ id: string; job_type: string; status: string }>; label?: (job: { id: string }) => string | null }) {
  if (jobs.length === 0) return null
  return (
    <div className={styles.jobList}>
      {jobs.slice(0, 3).map(job => (
        <div key={job.id} className={styles.jobItem}>
          <span>{job.job_type}</span>
          <b>{label?.(job) ?? jobStatusLabel(job)}</b>
        </div>
      ))}
    </div>
  )
}

function TagsSection({ note, refresh }: { note: Note; refresh: () => void }) {
  const [tagName, setTagName] = useState('')
  const contentTags = useQuery({ queryKey: ['content-tags', note.id], queryFn: () => fetchContentTags(note.id) })
  const suggestions = useQuery({ queryKey: ['content-tag-suggestions', note.id], queryFn: () => fetchContentTagSuggestions(note.id) })
  const jobs = useQuery({
    queryKey: ['content-tag-jobs', note.id],
    queryFn: () => fetchContentTagJobs(note.id),
    refetchInterval: pollWhileActive,
  })

  const addTag = useMutation({
    mutationFn: async (name: string) => assignExistingTagToContent(note.id, (await createOrFindTag(name)).id),
    onSuccess: () => {
      setTagName('')
      refresh()
    },
  })
  const accept = useMutation({ mutationFn: (id: string) => acceptTagSuggestion(note.id, id), onSettled: refresh })
  const reject = useMutation({ mutationFn: (id: string) => rejectTagSuggestion(note.id, id), onSettled: refresh })

  const accepted = contentTags.data?.filter(item => item.status === 'accepted').map(item => item.tag) ?? []
  const shownTags = accepted.length > 0 ? accepted : note.tags
  const submit = () => {
    const trimmed = tagName.trim()
    if (trimmed) addTag.mutate(trimmed)
  }

  return (
    <div className={styles.enrichmentColumn}>
      <div className={styles.enrichmentHeader}>
        <TagIcon size={14} />
        <span>Теги</span>
      </div>
      <div className={styles.chipRow}>
        <TagChips tags={shownTags} />
        {shownTags.length === 0 && <span className={styles.emptyText}>Нет тегов</span>}
      </div>
      {(suggestions.data?.length ?? 0) > 0 && (
        <div className={styles.suggestionList}>
          {suggestions.data!.map(item => (
            <SuggestionRow
              key={item.id}
              label={item.tag.name}
              confidence={item.confidence}
              onAccept={() => accept.mutate(item.id)}
              onReject={() => reject.mutate(item.id)}
            />
          ))}
        </div>
      )}
      <JobList jobs={jobs.data ?? []} />
      <div className={styles.inlineForm}>
        <input
          value={tagName}
          onChange={event => setTagName(event.target.value)}
          onKeyDown={event => { if (event.key === 'Enter') submit() }}
          placeholder="Новый тег"
        />
        <button type="button" onClick={submit} disabled={addTag.isPending || !tagName.trim()} title="Добавить тег">
          <Plus size={14} />
        </button>
      </div>
      {addTag.error && <div className={styles.enrichmentError}>{addTag.error.message}</div>}
    </div>
  )
}

function CategorySection({ note, refresh }: { note: Note; refresh: () => void }) {
  const [categoryQuery, setCategoryQuery] = useState('')
  const [categorySearch, setCategorySearch] = useState('')
  const assignments = useQuery({ queryKey: ['taxonomy-assignments', note.id], queryFn: () => fetchTaxonomyAssignments(note.id) })
  const jobs = useQuery({
    queryKey: ['taxonomy-classification-jobs', note.id],
    queryFn: () => fetchTaxonomyClassificationJobs(note.id),
    refetchInterval: pollWhileActive,
  })
  const categories = useQuery({
    queryKey: ['taxonomy-category-search', categorySearch],
    queryFn: () => searchTaxonomyCategories(categorySearch),
    enabled: categorySearch.length > 0,
  })

  const resetSearch = () => {
    setCategoryQuery('')
    setCategorySearch('')
    refresh()
  }
  const assign = useMutation({ mutationFn: (id: string) => assignCategoryToContent(note.id, id), onSuccess: resetSearch })
  const createAndAssign = useMutation({
    mutationFn: async (name: string) => assignCategoryToContent(note.id, (await createTaxonomyCategory(name)).id),
    onSuccess: resetSearch,
  })
  const accept = useMutation({ mutationFn: (id: string) => acceptTaxonomyAssignment(note.id, id), onSettled: refresh })
  const reject = useMutation({ mutationFn: (id: string) => rejectTaxonomyAssignment(note.id, id), onSettled: refresh })

  const items = assignments.data ?? []
  const current = items.find(item => item.is_current) ?? null
  const proposed = items.filter(item => item.status === 'proposed')
  const category: TaxonomyCategory | null = note.taxonomyCategory ?? (current
    ? {
        id: current.category_id,
        name: current.category_name_snapshot,
        slug: current.category_path_snapshot.split('/').pop() ?? current.category_id,
        path: current.category_path_snapshot,
      }
    : null)
  const jobResult = new Map((jobs.data ?? []).map(job => [job.id, job.result_status]))
  const error = assign.error ?? createAndAssign.error
  const search = () => {
    const trimmed = categoryQuery.trim()
    if (trimmed) setCategorySearch(trimmed)
  }

  return (
    <div className={styles.enrichmentColumn}>
      <div className={styles.enrichmentHeader}>
        <FolderTree size={14} />
        <span>Категория</span>
      </div>
      {category ? (
        <div className={styles.categoryPill}>
          <strong>{category.name}</strong>
          <span>{category.path}</span>
        </div>
      ) : <span className={styles.emptyText}>Нет категории</span>}
      {proposed.length > 0 && (
        <div className={styles.suggestionList}>
          {proposed.map(item => (
            <SuggestionRow
              key={item.id}
              label={item.category_name_snapshot}
              confidence={item.confidence}
              onAccept={() => accept.mutate(item.id)}
              onReject={() => reject.mutate(item.id)}
            />
          ))}
        </div>
      )}
      <JobList jobs={jobs.data ?? []} label={job => jobResult.get(job.id) ?? null} />
      <div className={styles.inlineForm}>
        <input
          value={categoryQuery}
          onChange={event => setCategoryQuery(event.target.value)}
          onKeyDown={event => { if (event.key === 'Enter') search() }}
          placeholder="Поиск категории"
        />
        <button type="button" onClick={search} disabled={!categoryQuery.trim()} title="Найти категорию">
          <Search size={14} />
        </button>
      </div>
      {categories.data && (
        <div className={styles.categoryResults}>
          {categories.data.map(item => (
            <button type="button" key={item.id} onClick={() => assign.mutate(item.id)}>
              <span>{item.name}</span>
              <small>{item.path}</small>
            </button>
          ))}
          {categories.data.length === 0 && (
            <button type="button" onClick={() => createAndAssign.mutate(categorySearch)}>
              <span>Создать категорию</span>
              <small>{categorySearch}</small>
            </button>
          )}
        </div>
      )}
      {!categories.data && categoryQuery.trim() && (
        <button
          type="button"
          className={styles.createCategoryBtn}
          onClick={() => createAndAssign.mutate(categoryQuery.trim())}
          disabled={createAndAssign.isPending}
        >
          <Plus size={13} />
          Создать и назначить
        </button>
      )}
      {error && <div className={styles.enrichmentError}>{error.message}</div>}
    </div>
  )
}

/** Tags and taxonomy category of a note: current values, AI suggestions, manual editing. */
export function EnrichmentPanel({ note }: { note: Note }) {
  const refresh = useEnrichmentRefresh(note.id)
  return (
    <section className={styles.enrichmentPanel}>
      <TagsSection note={note} refresh={refresh} />
      <CategorySection note={note} refresh={refresh} />
    </section>
  )
}
