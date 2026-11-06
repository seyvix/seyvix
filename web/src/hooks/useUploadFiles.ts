import { useMutation, useQueryClient } from '@tanstack/react-query'
import { uploadNoteFiles } from '../api/notes'
import { useLocalNotes } from '../contexts/LocalNotesContext'
import { useUploadContext } from '../contexts/UploadContext'
import { makeMarkdownTitle } from '../utils/markdownTitle'
import { SEARCH_CAPABILITIES_QUERY_KEY } from './useSearchCapabilities'
import { requestChangeFeedSync } from './useNotesChangeFeed'
import { type NotesQueryData, upsertNoteInNotesQueryData } from './useNotes'
import type { Note, NoteObject, NoteObjectType } from '../types'

function makeTempId() {
  return `local-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

function fileToObject(file: File, index: number): NoteObject {
  const type: NoteObjectType = file.type.startsWith('image/') ? 'image' : 'document'
  return { id: `tmp-obj-${index}`, type, content: URL.createObjectURL(file), createdAt: new Date().toISOString() }
}

/** Frees the object URLs of an optimistic card once the server's version replaces it. */
export function revokeLocalPreviewUrls(objects: NoteObject[]): void {
  for (const object of objects) {
    if (object.content.startsWith('blob:')) URL.revokeObjectURL(object.content)
  }
}

export function useUploadFiles() {
  const queryClient = useQueryClient()
  const { addLocalNote, updateLocalNote } = useLocalNotes()
  const { pushNotice } = useUploadContext()

  return useMutation({
    mutationFn: ({ files, text }: { files: File[]; text?: string }) => uploadNoteFiles(files, text),

    onMutate: ({ files, text }) => {
      const stableKey = makeTempId()
      const now = new Date().toISOString()
      const fileObjects = files.map((f, i) => fileToObject(f, i))
      const objects: NoteObject[] = text
        ? [...fileObjects, { id: 'tmp-text-0', type: 'text', content: text, createdAt: now }]
        : fileObjects
      // Mirror backend kind logic: document files → complex (composite)
      const singleFileIsDoc = files.length === 1 && !files[0].type.startsWith('image/')
      const type = (text && files.length === 1) ? 'composite'
                 : files.length > 1              ? 'collection'
                 : singleFileIsDoc               ? 'composite'
                 : 'simple'
      const optimistic: Note = {
        id: stableKey,
        slug: stableKey,
        stableKey,
        type,
        title: text ? makeMarkdownTitle(text) : files[0]?.name || '',
        cover: fileObjects.find(o => o.type === 'image')?.content ?? null,
        tags: [],
        taxonomyCategory: null,
        folderId: null,
        objects,
        createdAt: now,
        updatedAt: now,
        isLocal: true,
        isLoading: true,
      }
      addLocalNote(optimistic, { files, fileText: text })
      return { stableKey, fileObjects }
    },

    onSuccess: (serverNote, _vars, ctx) => {
      // The upload response is the stored note (assets, type, processing flag): no refetch.
      updateLocalNote(ctx.stableKey, { ...serverNote, stableKey: ctx.stableKey, isLoading: false, isLocal: false })
      queryClient.setQueriesData<NotesQueryData>({ queryKey: ['notes'] }, old =>
        upsertNoteInNotesQueryData(old, { ...serverNote, stableKey: ctx.stableKey }),
      )
      void queryClient.invalidateQueries({ queryKey: SEARCH_CAPABILITIES_QUERY_KEY })
      revokeLocalPreviewUrls(ctx.fileObjects)
      requestChangeFeedSync()
    },

    onError: (error, _vars, ctx) => {
      if (!ctx) return
      // The card stays as an unsynced local note (with its previews) so the user can retry.
      updateLocalNote(ctx.stableKey, { isLoading: false, isLocal: true })
      pushNotice(error instanceof Error ? error.message : 'Не удалось загрузить файлы')
    },
  })
}
