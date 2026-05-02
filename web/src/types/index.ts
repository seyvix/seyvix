export type NoteType = 'simple' | 'composite' | 'collection'

export type NoteObjectType = 'text' | 'image' | 'link' | 'document' | 'audio' | 'video'

export type SnapshotViewKind = 'thumbnail' | 'markdown' | 'pdf' | 'html'

export interface SnapshotView {
  kind: SnapshotViewKind
  label: string
  url: string
}

export interface Tag {
  id: string
  name: string
  slug?: string
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
  parentId: string | null
  children: Folder[]
}

export interface NoteObject {
  id: string
  type: NoteObjectType
  content: string
  cover?: string
  thumbnailUrl?: string | null
  thumbnailText?: string | null
  snapshotViews?: SnapshotView[]
  filename?: string      // оригинальное имя файла (для документов)
  mimeType?: string | null
  sizeBytes?: number
  slug?: string          // slug дочерней заметки (для элементов коллекции)
  createdAt: string
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
  /** Стабильный ключ для React — не меняется при tempId→serverId переходе */
  stableKey?: string
  isLocal?: boolean    // хранится локально, ещё не синхронизировано
  isLoading?: boolean  // запрос в процессе
}

export interface NotesParams {
  search?: string
  tags?: string[]
  folders?: string[]
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
