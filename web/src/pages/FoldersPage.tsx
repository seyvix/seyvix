import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, NavLink, useNavigate, useParams } from 'react-router-dom'
import {
  ArrowRight,
  Archive,
  ChevronDown,
  ChevronRight,
  Check,
  Edit3,
  FileText,
  Hash,
  Layers3,
  ListTree,
  MoreHorizontal,
  PanelRightOpen,
  Plus,
  Search,
  Sparkles,
  Tags,
  X,
} from 'lucide-react'
import {
  archiveCategory,
  createCategory,
  deleteCategory,
  fetchCategoryProfile,
  fetchTaxonomySettings,
  reclassifyInbox,
  suggestCategoryProfile,
  updateCategory,
  updateCategoryProfile,
} from '../api/folders'
import { useFolder } from '../hooks/useFolder'
import { useFolders } from '../hooks/useFolders'
import type { CategoryProfile, CategoryProfileDraft, Folder, FolderNoteSummary } from '../types'
import styles from './FoldersPage.module.css'

function categoryUrl(path: string): string {
  return `/categories/${path.split('/').map(encodeURIComponent).join('/')}`
}

function notesUrl(path: string): string {
  return `/notes?folders=${encodeURIComponent(path)}`
}

function countCategories(categories: Folder[]): number {
  return categories.reduce((total, category) => total + 1 + countCategories(category.children), 0)
}

function findCategory(categories: Folder[], path: string): Folder | null {
  for (const category of categories) {
    if (category.path === path) return category
    const child = findCategory(category.children, path)
    if (child) return child
  }
  return null
}

function ancestorPaths(path: string): string[] {
  const segments = path.split('/').filter(Boolean)
  return segments.slice(0, -1).map((_, index) => segments.slice(0, index + 1).join('/'))
}

function listToText(values: string[]): string {
  return values.join('\n')
}

function textToList(value: string): string[] {
  return value
    .split(/\n|,/)
    .map(item => item.trim())
    .filter(Boolean)
}

function profileFormFrom(profile: CategoryProfile | CategoryProfileDraft | undefined) {
  return {
    summary: profile?.summary ?? '',
    keywords: listToText(profile?.keywords ?? []),
    positiveExamples: listToText(profile?.positiveExamples ?? []),
    negativeExamples: listToText(profile?.negativeExamples ?? []),
  }
}

function formToProfile(form: ReturnType<typeof profileFormFrom>) {
  return {
    summary: form.summary.trim() || null,
    keywords: textToList(form.keywords),
    positiveExamples: textToList(form.positiveExamples),
    negativeExamples: textToList(form.negativeExamples),
  }
}

function Breadcrumbs({ category }: { category: Folder }) {
  const segments = category.path.split('/')
  const crumbs = segments.map((segment, index) => ({
    label: segment,
    path: segments.slice(0, index + 1).join('/'),
  }))

  return (
    <div className={styles.breadcrumbs} aria-label="Путь категории">
      {crumbs.map((crumb, index) => (
        <span key={crumb.path} className={styles.crumb}>
          {index > 0 && <ChevronRight size={13} strokeWidth={1.8} />}
          <Link to={categoryUrl(crumb.path)}>{crumb.label}</Link>
        </span>
      ))}
    </div>
  )
}

function CategoryTreeNode({
  category,
  depth,
  expandedPaths,
  selectedPath,
  onToggle,
}: {
  category: Folder
  depth: number
  expandedPaths: Set<string>
  selectedPath: string
  onToggle: (path: string) => void
}) {
  const hasChildren = category.children.length > 0
  const expanded = expandedPaths.has(category.path)

  return (
    <div>
      <div
        className={[
          styles.treeRow,
          selectedPath === category.path ? styles.treeRowActive : '',
        ].filter(Boolean).join(' ')}
        style={{ '--depth': depth } as CSSProperties}
      >
        <button
          className={styles.treeToggle}
          disabled={!hasChildren}
          onClick={() => onToggle(category.path)}
          aria-label={expanded ? 'Свернуть категорию' : 'Развернуть категорию'}
        >
          {hasChildren && (
            expanded ? <ChevronDown size={14} strokeWidth={1.8} /> : <ChevronRight size={14} strokeWidth={1.8} />
          )}
        </button>
        <NavLink
          to={categoryUrl(category.path)}
          className={({ isActive }) =>
            [styles.treeItem, isActive || selectedPath === category.path ? styles.treeItemActive : '']
              .filter(Boolean)
              .join(' ')
          }
        >
          <span className={styles.treeRail} />
          <span className={styles.treeName}>{category.name}</span>
          <span className={styles.treeCount}>{category.totalCount}</span>
        </NavLink>
      </div>

      {hasChildren && expanded && (
        <div className={styles.treeChildren}>
          {category.children.map(child => (
            <CategoryTreeNode
              key={child.id}
              category={child}
              depth={depth + 1}
              expandedPaths={expandedPaths}
              selectedPath={selectedPath}
              onToggle={onToggle}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function CategoryCard({ category }: { category: Folder }) {
  return (
    <Link to={categoryUrl(category.path)} className={styles.categoryCard}>
      <span className={styles.categoryCardIcon}><Tags size={16} strokeWidth={1.8} /></span>
      <span className={styles.categoryCardBody}>
        <strong>{category.name}</strong>
        <small>{category.path}</small>
      </span>
      <ArrowRight size={15} strokeWidth={1.8} />
    </Link>
  )
}

function NoteRow({ note, selectedPath }: { note: FolderNoteSummary; selectedPath: string }) {
  const notePath = note.taxonomyCategory?.path
  const isNested = Boolean(notePath && notePath !== selectedPath)

  return (
    <Link to={`/notes/${note.slug}`} className={styles.noteRow}>
      <span className={styles.noteIcon}><FileText size={15} strokeWidth={1.8} /></span>
      <span className={styles.noteBody}>
        <strong>{note.title}</strong>
        <small>{new Date(note.updatedAt).toLocaleDateString('ru-RU')}</small>
      </span>
      {isNested && <span className={styles.noteCategory}>{notePath}</span>}
      <ArrowRight size={14} strokeWidth={1.8} />
    </Link>
  )
}

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

export default function FoldersPage() {
  const { '*': selectedPath = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(() => new Set())
  const [profileEditing, setProfileEditing] = useState(false)
  const [profileForm, setProfileForm] = useState(() => profileFormFrom(undefined))
  const [profileGuidance, setProfileGuidance] = useState('')
  const [profileDraft, setProfileDraft] = useState<CategoryProfileDraft | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [createName, setCreateName] = useState('')
  const [createDescription, setCreateDescription] = useState('')
  const [renameOpen, setRenameOpen] = useState(false)
  const [renameName, setRenameName] = useState('')
  const [moreOpen, setMoreOpen] = useState(false)
  const [profileSidebarOpen, setProfileSidebarOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteConfirmName, setDeleteConfirmName] = useState('')
  const [deleteConfirmText, setDeleteConfirmText] = useState('')
  const { data: categories = [], isPending: treePending, isError: treeError } = useFolders()
  const {
    data: detail,
    isPending: detailPending,
    isError: detailError,
  } = useFolder(selectedPath)
  const selectedFromTree = useMemo(
    () => selectedPath ? findCategory(categories, selectedPath) : null,
    [categories, selectedPath],
  )
  const selectedCategory = detail?.category ?? selectedFromTree
  const taxonomySettings = useQuery({
    queryKey: ['taxonomy-settings'],
    queryFn: fetchTaxonomySettings,
  })
  const categoryProfile = useQuery({
    queryKey: ['category-profile', selectedCategory?.id],
    queryFn: () => fetchCategoryProfile(selectedCategory?.id ?? ''),
    enabled: Boolean(selectedCategory?.id),
  })
  const reclassify = useMutation({
    mutationFn: reclassifyInbox,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['category', 'inbox'] })
    },
  })
  const saveProfile = useMutation({
    mutationFn: (form: ReturnType<typeof profileFormFrom>) =>
      updateCategoryProfile(selectedCategory?.id ?? '', formToProfile(form)),
    onSuccess: async () => {
      setProfileEditing(false)
      setProfileDraft(null)
      await queryClient.invalidateQueries({ queryKey: ['category-profile', selectedCategory?.id] })
    },
  })
  const suggestProfile = useMutation({
    mutationFn: () => suggestCategoryProfile(selectedCategory?.id ?? '', profileGuidance),
    onSuccess: (draft) => setProfileDraft(draft),
  })
  const createCategoryMutation = useMutation({
    mutationFn: () => createCategory({
      name: createName,
      parentId: selectedCategory?.id ?? null,
      description: createDescription,
    }),
    onSuccess: async (category) => {
      setCreateOpen(false)
      setCreateName('')
      setCreateDescription('')
      await queryClient.invalidateQueries({ queryKey: ['folders'] })
      navigate(categoryUrl(category.path))
    },
  })
  const renameCategoryMutation = useMutation({
    mutationFn: () => updateCategory(selectedCategory?.id ?? '', { name: renameName }),
    onSuccess: async (category) => {
      setRenameOpen(false)
      await queryClient.invalidateQueries({ queryKey: ['folders'] })
      await queryClient.invalidateQueries({ queryKey: ['category', selectedPath] })
      navigate(categoryUrl(category.path))
    },
  })
  const archiveCategoryMutation = useMutation({
    mutationFn: () => archiveCategory(selectedCategory?.id ?? ''),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['folders'] })
      navigate('/categories')
    },
  })
  const deleteCategoryMutation = useMutation({
    mutationFn: (payload: {
      deleteNotes?: boolean
      confirmCategoryName?: string
      confirmDeleteNotesText?: string
    }) => deleteCategory(selectedCategory?.id ?? '', payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['folders'] })
      navigate('/categories')
    },
  })

  const totalCategories = useMemo(() => countCategories(categories), [categories])
  const childCategories = selectedFromTree?.children ?? selectedCategory?.children ?? categories
  const notes = detail?.notes ?? []
  const popularTags = (detail?.tags ?? []).slice(0, 12)
  const profile = categoryProfile.data
  const profileEditingAllowed = taxonomySettings.data?.categoryProfileEditingEnabled === true

  useEffect(() => {
    if (!selectedPath) return
    setExpandedPaths(prev => {
      const next = new Set(prev)
      ancestorPaths(selectedPath).forEach(path => next.add(path))
      return next
    })
  }, [selectedPath])

  useEffect(() => {
    setProfileForm(profileFormFrom(profile))
    setProfileEditing(false)
    setProfileDraft(null)
    setProfileGuidance('')
    setRenameName(selectedCategory?.name ?? '')
    setRenameOpen(false)
    setMoreOpen(false)
    setDeleteOpen(false)
    setDeleteConfirmName('')
    setDeleteConfirmText('')
    setProfileSidebarOpen(false)
    setCreateOpen(false)
    setCreateName('')
    setCreateDescription('')
  }, [profile, selectedCategory?.id])

  useEffect(() => {
    if (profileEditingAllowed) return
    setProfileEditing(false)
    setProfileDraft(null)
    setProfileGuidance('')
  }, [profileEditingAllowed])

  function handleToggle(path: string) {
    setExpandedPaths(prev => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  function updateProfileForm(field: keyof ReturnType<typeof profileFormFrom>, value: string) {
    setProfileForm(prev => ({ ...prev, [field]: value }))
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <div className={styles.kicker}>
            <Layers3 size={15} strokeWidth={1.8} />
            Таксономия базы знаний
          </div>
          <h1>Категории</h1>
        </div>
        <div className={styles.headerStats}>
          <div className={styles.stat}>
            <strong>{totalCategories}</strong>
            <span>категорий</span>
          </div>
          <div className={styles.stat}>
            <strong>{categories.length}</strong>
            <span>корневых</span>
          </div>
        </div>
      </header>

      <div className={styles.shell}>
        <aside className={styles.sidebarPanel}>
          <div className={styles.panelHeader}>
            <ListTree size={16} strokeWidth={1.8} />
            <span>Дерево</span>
          </div>
          {treePending && <div className={styles.state}>Загружаю категории...</div>}
          {treeError && <div className={styles.stateError}>Не удалось загрузить категории.</div>}
          {!treePending && !treeError && (
            <nav className={styles.tree} aria-label="Категории">
              {categories.length === 0 ? (
                <div className={styles.emptyTree}>
                  <ListTree size={18} strokeWidth={1.8} />
                  <span>Категории появятся после настройки таксономии.</span>
                </div>
              ) : categories.map(category => (
                <CategoryTreeNode
                  key={category.id}
                  category={category}
                  depth={0}
                  expandedPaths={expandedPaths}
                  selectedPath={selectedPath}
                  onToggle={handleToggle}
                />
              ))}
            </nav>
          )}
        </aside>

        <main className={styles.contentPanel}>
          {!selectedCategory && (
            <section className={styles.overview}>
              <div className={styles.overviewIntro}>
                <div className={styles.overviewIcon}><Search size={18} strokeWidth={1.8} /></div>
                <div>
                  <h2>Выберите категорию</h2>
                  <p>Откройте раздел дерева слева или начните с одной из корневых категорий.</p>
                </div>
              </div>

              <div className={styles.managementPanel}>
                <div className={styles.sectionHeader}>
                  <h3>Новая корневая категория</h3>
                  <button className={styles.secondaryAction} onClick={() => setCreateOpen(value => !value)}>
                    <Plus size={15} strokeWidth={1.8} />
                    Создать
                  </button>
                </div>
                {createOpen && (
                  <div className={styles.categoryForm}>
                    <input
                      value={createName}
                      onChange={event => setCreateName(event.target.value)}
                      placeholder="Название"
                    />
                    <input
                      value={createDescription}
                      onChange={event => setCreateDescription(event.target.value)}
                      placeholder="Описание"
                    />
                    <button
                      className={styles.primaryAction}
                      disabled={!createName.trim() || createCategoryMutation.isPending}
                      onClick={() => createCategoryMutation.mutate()}
                    >
                      <Check size={15} strokeWidth={1.8} />
                      Сохранить
                    </button>
                  </div>
                )}
                {createCategoryMutation.isError && <div className={styles.stateError}>Не удалось создать категорию.</div>}
              </div>

              <div className={styles.sectionHeader}>
                <h3>Корневые категории</h3>
                <span>{categories.length}</span>
              </div>
              <div className={styles.categoryGrid}>
                {categories.map(category => (
                  <CategoryCard key={category.id} category={category} />
                ))}
              </div>
            </section>
          )}

          {selectedCategory && (
            <section className={styles.detail}>
              <div className={styles.detailHeader}>
                <div>
                  <Breadcrumbs category={selectedCategory} />
                  <h2>{selectedCategory.name}</h2>
                  <p>{selectedCategory.path}</p>
                </div>
                <div className={styles.detailHeaderActions}>
                  <button
                    className={styles.secondaryAction}
                    onClick={() => setProfileSidebarOpen(true)}
                  >
                    <PanelRightOpen size={16} strokeWidth={1.8} />
                    Профиль
                  </button>
                  <Link className={styles.primaryAction} to={notesUrl(selectedCategory.path)}>
                    <FileText size={16} strokeWidth={1.8} />
                    Заметки
                  </Link>
                  {selectedCategory.path === 'inbox' && (
                  <button
                    className={styles.secondaryAction}
                    disabled={reclassify.isPending}
                    onClick={() => reclassify.mutate()}
                  >
                    <Layers3 size={16} strokeWidth={1.8} />
                    {reclassify.isPending ? 'Запускаю...' : 'Перераспределить'}
                  </button>
                  )}
                </div>
              </div>

              {detailPending && <div className={styles.state}>Загружаю содержимое категории...</div>}
              {detailError && <div className={styles.stateError}>Не удалось загрузить содержимое категории.</div>}
              {reclassify.isSuccess && selectedCategory.path === 'inbox' && (
                <div className={styles.state}>
                  В очередь отправлено: {reclassify.data.enqueuedCount}
                </div>
              )}
              {reclassify.isError && selectedCategory.path === 'inbox' && (
                <div className={styles.stateError}>Не удалось запустить перераспределение inbox.</div>
              )}
              {renameCategoryMutation.isError && (
                <div className={styles.stateError}>Не удалось переименовать категорию.</div>
              )}
              {archiveCategoryMutation.isError && (
                <div className={styles.stateError}>Не удалось архивировать категорию. Проверьте, нет ли вложенных категорий.</div>
              )}
              {deleteCategoryMutation.isError && (
                <div className={styles.stateError}>Не удалось удалить категорию.</div>
              )}

              <div className={styles.managementPanel}>
                <div className={styles.managementActions}>
                  <button className={styles.secondaryAction} onClick={() => setCreateOpen(value => !value)}>
                    <Plus size={15} strokeWidth={1.8} />
                    Подкатегория
                  </button>
                  <button className={styles.secondaryAction} onClick={() => setRenameOpen(value => !value)}>
                    <Edit3 size={15} strokeWidth={1.8} />
                    Переименовать
                  </button>
                  <div className={styles.moreMenuWrap}>
                    <button className={styles.secondaryAction} onClick={() => setMoreOpen(value => !value)}>
                      <MoreHorizontal size={15} strokeWidth={1.8} />
                      Ещё
                    </button>
                    {moreOpen && (
                      <div className={styles.moreMenu}>
                        <button
                          disabled={selectedCategory.path === 'inbox' || archiveCategoryMutation.isPending}
                          onClick={() => archiveCategoryMutation.mutate()}
                        >
                          <Archive size={15} strokeWidth={1.8} />
                          Архивировать
                        </button>
                        <button
                          className={styles.moreDanger}
                          disabled={selectedCategory.path === 'inbox' || deleteCategoryMutation.isPending}
                          onClick={() => {
                            setDeleteOpen(value => !value)
                            setMoreOpen(false)
                          }}
                        >
                          <X size={15} strokeWidth={1.8} />
                          Удалить
                        </button>
                      </div>
                    )}
                  </div>
                </div>

                {createOpen && (
                  <div className={styles.categoryForm}>
                    <input
                      value={createName}
                      onChange={event => setCreateName(event.target.value)}
                      placeholder="Название подкатегории"
                    />
                    <input
                      value={createDescription}
                      onChange={event => setCreateDescription(event.target.value)}
                      placeholder="Описание"
                    />
                    <button
                      className={styles.primaryAction}
                      disabled={!createName.trim() || createCategoryMutation.isPending}
                      onClick={() => createCategoryMutation.mutate()}
                    >
                      <Check size={15} strokeWidth={1.8} />
                      Создать
                    </button>
                  </div>
                )}

                {renameOpen && (
                  <div className={styles.categoryForm}>
                    <input
                      value={renameName}
                      onChange={event => setRenameName(event.target.value)}
                      placeholder="Новое название"
                    />
                    <button
                      className={styles.primaryAction}
                      disabled={!renameName.trim() || renameCategoryMutation.isPending}
                      onClick={() => renameCategoryMutation.mutate()}
                    >
                      <Check size={15} strokeWidth={1.8} />
                      Сохранить
                    </button>
                  </div>
                )}

                {deleteOpen && (
                  <div className={styles.deletePanel}>
                    <div className={styles.deletePanelHeader}>
                      <strong>Удаление категории</strong>
                      <span>По умолчанию заметки из этой категории и её подкатегорий будут перенесены в Inbox.</span>
                    </div>
                    <button
                      className={styles.dangerAction}
                      disabled={deleteCategoryMutation.isPending}
                      onClick={() => deleteCategoryMutation.mutate({ deleteNotes: false })}
                    >
                      <X size={15} strokeWidth={1.8} />
                      Удалить категорию
                    </button>

                    <div className={styles.dangerDeleteBlock}>
                      <div className={styles.deletePanelHeader}>
                        <strong>Удалить вместе с заметками</strong>
                        <span>Это отдельный режим: введите название и полный путь категории, чтобы подтвердить удаление содержимого.</span>
                      </div>
                      <div className={styles.categoryForm}>
                        <input
                          value={deleteConfirmName}
                          onChange={event => setDeleteConfirmName(event.target.value)}
                          placeholder={`Название: ${selectedCategory.name}`}
                        />
                        <input
                          value={deleteConfirmText}
                          onChange={event => setDeleteConfirmText(event.target.value)}
                          placeholder={`Путь: ${selectedCategory.path}`}
                        />
                      </div>
                      <button
                        className={styles.dangerAction}
                        disabled={
                          deleteCategoryMutation.isPending
                          || deleteConfirmName !== selectedCategory.name
                          || deleteConfirmText !== selectedCategory.path
                        }
                        onClick={() => deleteCategoryMutation.mutate({
                          deleteNotes: true,
                          confirmCategoryName: deleteConfirmName,
                          confirmDeleteNotesText: deleteConfirmText,
                        })}
                      >
                        <X size={15} strokeWidth={1.8} />
                        Удалить категорию и заметки
                      </button>
                    </div>
                  </div>
                )}
              </div>

              <div className={styles.detailGrid}>
                <section className={styles.detailBlock}>
                  <div className={styles.sectionHeader}>
                    <h3>Вложенные категории</h3>
                    <span>{childCategories.length}</span>
                  </div>
                  {childCategories.length > 0 ? (
                    <div className={styles.categoryGrid}>
                      {childCategories.map(category => (
                        <CategoryCard key={category.id} category={category} />
                      ))}
                    </div>
                  ) : (
                    <div className={styles.emptyBlock}>У этой категории пока нет дочерних категорий.</div>
                  )}
                </section>

                <section className={styles.detailBlock}>
                  <div className={styles.sectionHeader}>
                    <h3>Популярные теги</h3>
                    <span>{detail?.tags.length ?? 0}</span>
                  </div>
                  {popularTags.length ? (
                    <div className={styles.tags}>
                      {popularTags.map(tag => (
                        <Link key={tag.id} to={`/notes?tags=${encodeURIComponent(tag.slug ?? tag.name)}`} className={styles.tag}>
                          <Hash size={13} strokeWidth={1.8} />
                          <span>{tag.name}</span>
                          <small>{tag.count ?? 0}</small>
                        </Link>
                      ))}
                    </div>
                  ) : (
                    <div className={styles.emptyBlock}>Теги появятся, когда в категории будут заметки.</div>
                  )}
                </section>

                <section className={styles.detailBlockWide}>
                  <div className={styles.sectionHeader}>
                    <h3>Заметки</h3>
                    <span>{selectedCategory.directCount} / {selectedCategory.totalCount}</span>
                  </div>
                  {notes.length > 0 ? (
                    <div className={styles.notesList}>
                      {notes.map(note => (
                        <NoteRow key={note.id} note={note} selectedPath={selectedCategory.path} />
                      ))}
                    </div>
                  ) : (
                    <div className={styles.emptyBlock}>В этой категории пока нет заметок.</div>
                  )}
                </section>
              </div>

              {profileSidebarOpen && (
                <>
                  <button
                    className={styles.profileScrim}
                    aria-label="Закрыть профиль категории"
                    onClick={() => setProfileSidebarOpen(false)}
                  />
                  <aside className={styles.profileSidebar} aria-label="LLM-профиль категории">
                    <div className={styles.profileSidebarHeader}>
                      <div>
                        <span>{profileEditingAllowed ? 'редактирование включено' : 'только просмотр'}</span>
                        <h3>LLM-профиль</h3>
                      </div>
                      <button className={styles.iconAction} onClick={() => setProfileSidebarOpen(false)} aria-label="Закрыть профиль">
                        <X size={17} strokeWidth={1.8} />
                      </button>
                    </div>

                    {categoryProfile.isLoading && <div className={styles.emptyBlock}>Загружаю профиль категории...</div>}
                    {categoryProfile.isError && <div className={styles.stateError}>Не удалось загрузить профиль категории.</div>}
                    {!categoryProfile.isLoading && !categoryProfile.isError && (
                      <div className={styles.profileBody}>
                        {!profileEditing && (
                          <>
                            <p className={styles.profileSummary}>
                              {profile?.summary || 'Описание профиля пока не заполнено.'}
                            </p>
                            <div className={styles.profileLists}>
                              <ProfileList title="Ключевые слова" values={profile?.keywords ?? []} />
                              <ProfileList title="Что подходит" values={profile?.positiveExamples ?? []} />
                              <ProfileList title="Что не подходит" values={profile?.negativeExamples ?? []} />
                            </div>
                          </>
                        )}

                        {profileEditing && (
                          <div className={styles.profileForm}>
                            <label>
                              <span>Summary</span>
                              <textarea value={profileForm.summary} onChange={event => updateProfileForm('summary', event.target.value)} />
                            </label>
                            <label>
                              <span>Keywords</span>
                              <textarea value={profileForm.keywords} onChange={event => updateProfileForm('keywords', event.target.value)} />
                            </label>
                            <label>
                              <span>Positive examples</span>
                              <textarea value={profileForm.positiveExamples} onChange={event => updateProfileForm('positiveExamples', event.target.value)} />
                            </label>
                            <label>
                              <span>Negative examples</span>
                              <textarea value={profileForm.negativeExamples} onChange={event => updateProfileForm('negativeExamples', event.target.value)} />
                            </label>
                          </div>
                        )}

                        <div className={styles.profileActions}>
                          {profileEditingAllowed && !profileEditing && (
                            <button className={styles.secondaryAction} onClick={() => setProfileEditing(true)}>
                              <Edit3 size={15} strokeWidth={1.8} />
                              Редактировать
                            </button>
                          )}
                          {profileEditing && (
                            <>
                              <button className={styles.primaryAction} disabled={saveProfile.isPending} onClick={() => saveProfile.mutate(profileForm)}>
                                <Check size={15} strokeWidth={1.8} />
                                Сохранить
                              </button>
                              <button className={styles.secondaryAction} onClick={() => { setProfileEditing(false); setProfileForm(profileFormFrom(profile)) }}>
                                <X size={15} strokeWidth={1.8} />
                                Отмена
                              </button>
                            </>
                          )}
                        </div>

                        {profileEditingAllowed && (
                          <>
                            <div className={styles.profileSuggest}>
                              <textarea
                                value={profileGuidance}
                                onChange={event => setProfileGuidance(event.target.value)}
                                placeholder="Опишите, что должно попадать в эту категорию или её подкатегории."
                              />
                              <button
                                className={styles.secondaryAction}
                                disabled={!profileGuidance.trim() || suggestProfile.isPending}
                                onClick={() => suggestProfile.mutate()}
                              >
                                <Sparkles size={15} strokeWidth={1.8} />
                                {suggestProfile.isPending ? 'Готовлю...' : 'Предложить улучшение'}
                              </button>
                            </div>

                            {suggestProfile.isError && <div className={styles.stateError}>Не удалось получить черновик профиля.</div>}
                            {saveProfile.isError && <div className={styles.stateError}>Не удалось сохранить профиль категории.</div>}

                            {profileDraft && (
                              <div className={styles.profileDraft}>
                                <div>
                                  <strong>{profileDraft.summary || 'Без summary'}</strong>
                                  <p>{profileDraft.reasoning}</p>
                                </div>
                                <div className={styles.profileLists}>
                                  <ProfileList title="Ключевые слова" values={profileDraft.keywords} />
                                  <ProfileList title="Что подходит" values={profileDraft.positiveExamples} />
                                  <ProfileList title="Что не подходит" values={profileDraft.negativeExamples} />
                                </div>
                                <div className={styles.profileActions}>
                                  <button className={styles.primaryAction} disabled={saveProfile.isPending} onClick={() => saveProfile.mutate(profileFormFrom(profileDraft))}>
                                    <Check size={15} strokeWidth={1.8} />
                                    Принять
                                  </button>
                                  <button className={styles.secondaryAction} onClick={() => setProfileDraft(null)}>
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
              )}
            </section>
          )}
        </main>
      </div>
    </div>
  )
}
