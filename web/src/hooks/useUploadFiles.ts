import { useMutation, useQueryClient } from '@tanstack/react-query'
import { startUploadJob, fetchNote } from '../api/notes'
import { useLocalNotes } from '../contexts/LocalNotesContext'
import type { Note, NoteObject, NoteObjectType } from '../types'

function makeTempId() {
  return `local-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

function fileToObject(file: File, index: number): NoteObject {
  const type: NoteObjectType = file.type.startsWith('image/') ? 'image' : 'document'
  return { id: `tmp-obj-${index}`, type, content: URL.createObjectURL(file), createdAt: new Date().toISOString() }
}

export function useUploadFiles() {
  const queryClient = useQueryClient()
  const { addLocalNote, updateLocalNote } = useLocalNotes()

  return useMutation({
    mutationFn: ({ files, text }: { files: File[]; text?: string }) => startUploadJob(files, text),

    onMutate: async ({ files, text }) => {
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
        title: text?.split('\n')[0].slice(0, 60) || files[0]?.name || '',
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
      return { stableKey, files, text, optimistic }
    },

    onSuccess: async ({ noteId, noteSlug }, _vars, ctx) => {
      // Fetch full note to get real asset URLs and correct type/objects
      try {
        const serverNote = await fetchNote(noteId)
        updateLocalNote(ctx.stableKey, {
          ...serverNote,
          stableKey: ctx.stableKey,
          isLoading: false,
          isLocal: false,
        })
        queryClient.setQueriesData<Note[]>({ queryKey: ['notes'] }, old =>
          Array.isArray(old)
            ? [{ ...serverNote, stableKey: ctx.stableKey }, ...old.filter(n => n.id !== serverNote.id)]
            : [serverNote],
        )
      } catch {
        updateLocalNote(ctx.stableKey, { id: noteId, slug: noteSlug, isLoading: false, isLocal: false })
        queryClient.invalidateQueries({ queryKey: ['notes'] })
      }
    },

    onError: (_err, _vars, ctx) => {
      if (!ctx) return
      updateLocalNote(ctx.stableKey, { isLoading: false, isLocal: true })
    },
  })
}
