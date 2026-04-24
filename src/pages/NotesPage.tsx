import { useNotes } from '../hooks/useNotes'
import { useUploadFiles } from '../hooks/useUploadFiles'
import { NoteGrid } from '../components/NoteGrid/NoteGrid'

export default function NotesPage() {
  const { data: notes = [], isPending } = useNotes()
  const { isPending: isUploading } = useUploadFiles()

  if (isPending) return null

  return <NoteGrid notes={notes} isUploading={isUploading} />
}
