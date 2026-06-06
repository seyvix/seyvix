import { useParams } from 'react-router'

export default function NoteEditPage() {
  const { noteId } = useParams<{ noteId: string }>()
  return <div>Edit Note: {noteId}</div>
}
