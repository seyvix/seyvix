import { useParams } from 'react-router-dom'

export default function NoteEditPage() {
  const { noteSlug } = useParams<{ noteSlug: string }>()
  return <div>Edit Note: {noteSlug}</div>
}
