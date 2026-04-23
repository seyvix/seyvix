export type NoteType = 'simple' | 'composite' | 'collection'

export type NoteObjectType = 'text' | 'image' | 'link' | 'document'

export interface Tag {
  id: string
  name: string
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
  createdAt: string
}

export interface Note {
  id: string
  slug: string
  type: NoteType
  title: string
  cover: string | null
  tags: Tag[]
  folderId: string | null
  objects: NoteObject[]
  createdAt: string
  updatedAt: string
}

export interface NotesParams {
  search?: string
  tags?: string[]
  folders?: string[]
}
