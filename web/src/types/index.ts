export type NoteType = 'simple' | 'composite' | 'collection'

export type NoteObjectType = 'text' | 'image' | 'link' | 'document' | 'audio' | 'video'

export type SnapshotViewKind = 'thumbnail' | 'markdown' | 'pdf' | 'html' | 'webpage_html'

export interface SnapshotView {
  kind: SnapshotViewKind
  label: string
  url: string
}

export interface SourceMetadata {
  provider: string
  providerLabel: string
  externalId: string
  url?: string | null
  title?: string | null
  originalCreatedAt?: string | null
  origin?: Record<string, unknown> | null
  author?: Record<string, unknown> | null
  groupId?: string | null
  entities?: Array<Record<string, unknown>>
  customEmojiIds?: string[]
  rawPayload?: Record<string, unknown> | null
  metadata?: Record<string, unknown>
}

export interface Tag {
  id: string
  name: string
  slug?: string
  count?: number
}

export interface TaxonomyCategory {
  id: string
  name: string
  slug: string
  path: string
}

export interface TaxonomyTreeItem extends TaxonomyCategory {
  depth: number
  description: string | null
  isSystem: boolean
  isArchived: boolean
  children: TaxonomyTreeItem[]
}

export interface TaxonomyInterestOption {
  slug: string
  name: string
  description: string
}

export interface Folder {
  id: string
  slug: string
  name: string
  path: string
  directCount: number
  totalCount: number
  parentId: string | null
  children: Folder[]
}

export interface FolderNoteSummary {
  id: string
  slug: string
  title: string
  taxonomyCategory?: TaxonomyCategory | null
  createdAt: string
  updatedAt: string
}

export interface FolderDetail {
  category: Folder
  tags: Tag[]
  notes: FolderNoteSummary[]
}

export interface TaxonomySettings {
  ownerUserId: string
  categoryProfileEditingEnabled: boolean
  trashEnabled: boolean
  trashRetentionDays: number
}

export interface CategoryProfile {
  id?: string
  categoryId: string
  summary: string | null
  keywords: string[]
  positiveExamples: string[]
  negativeExamples: string[]
  createdAt?: string
  updatedAt?: string
}

export interface CategoryProfileDraft {
  summary: string | null
  keywords: string[]
  positiveExamples: string[]
  negativeExamples: string[]
  reasoning: string
}

export interface NoteObject {
  id: string
  noteId?: string | null
  type: NoteObjectType
  content: string
  caption?: string | null
  cover?: string
  thumbnailUrl?: string | null
  thumbnailText?: string | null
  imageWidth?: number | null
  imageHeight?: number | null
  visualWidth?: number | null
  visualHeight?: number | null
  snapshotViews?: SnapshotView[]
  filename?: string      // оригинальное имя файла (для документов)
  mimeType?: string | null
  sizeBytes?: number
  slug?: string          // slug дочерней заметки (для элементов коллекции)
  source?: SourceMetadata | null
  createdAt: string
}

export interface NoteCollectionRef {
  id: string
  slug: string
  title: string
}

export interface SearchHighlightRange {
  start: number
  end: number
}

export interface SearchMatch {
  chunk_id?: string
  chunkId?: string
  chunk_external_id?: string
  chunkExternalId?: string
  text: string
  score: number
  highlight_ranges?: SearchHighlightRange[]
  highlightRanges?: SearchHighlightRange[]
}

export interface Note {
  id: string
  slug: string
  type: NoteType
  title: string
  cover: string | null
  tags: Tag[]
  taxonomyCategory?: TaxonomyCategory | null
  folderId: string | null
  objects: NoteObject[]
  createdAt: string
  updatedAt: string
  isFavorite?: boolean
  collection?: NoteCollectionRef | null
  source?: SourceMetadata | null
  searchMatches?: SearchMatch[]
  /** Стабильный ключ для React — не меняется при tempId→serverId переходе */
  stableKey?: string
  isLocal?: boolean    // хранится локально, ещё не синхронизировано
  isLoading?: boolean  // запрос в процессе
}

export interface NotesParams {
  search?: string
  searchMode?: 'full_text' | 'semantic' | 'hybrid'
  tags?: string[]
  folders?: string[]
  sort?: 'newest' | 'custom'
}

export interface FileProgress {
  name: string
  status: 'pending' | 'processing' | 'done' | 'error'
  progress: number  // 0–100
}

export interface UploadJob {
  id: string
  status: 'processing' | 'done' | 'error'
  files: FileProgress[]
  noteId?: string
}
