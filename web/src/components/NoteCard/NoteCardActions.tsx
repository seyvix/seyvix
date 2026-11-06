import { createContext, useContext, useMemo, type ReactNode } from 'react'
import { useAddFilesToNote } from '../../hooks/useAddFilesToNote'
import { useUploadFiles } from '../../hooks/useUploadFiles'
import { useUploadContext } from '../../contexts/UploadContext'
import { partitionUploadFiles } from '../../utils/uploadGuard'

interface NoteCardActions {
  /** Creates a new note from dropped files. */
  uploadFiles: (files: File[]) => void
  /** Appends dropped files to an existing note. */
  addFilesToNote: (noteId: string, files: File[]) => void
  /** Filters out unsupported files (reporting them) and returns the accepted ones. */
  acceptFiles: (files: File[]) => File[]
}

const NoteCardActionsContext = createContext<NoteCardActions | null>(null)

/**
 * Grid-level owner of the upload mutations so every card doesn't subscribe its own
 * mutation observers (60+ cards × 2 mutations before).
 */
export function NoteCardActionsProvider({ children }: { children: ReactNode }) {
  const { mutate: upload } = useUploadFiles()
  const { mutate: addFiles } = useAddFilesToNote()
  const { pushNotice } = useUploadContext()

  const value = useMemo<NoteCardActions>(() => ({
    uploadFiles: files => upload({ files }),
    addFilesToNote: (noteId, files) => addFiles({ noteId, files }),
    acceptFiles: files => {
      const { accepted, rejected } = partitionUploadFiles(files)
      for (const rejection of rejected) pushNotice(rejection.reason)
      return accepted
    },
  }), [addFiles, pushNotice, upload])

  return <NoteCardActionsContext.Provider value={value}>{children}</NoteCardActionsContext.Provider>
}

export function useNoteCardActions(): NoteCardActions {
  const value = useContext(NoteCardActionsContext)
  if (!value) throw new Error('useNoteCardActions must be used within NoteCardActionsProvider')
  return value
}
