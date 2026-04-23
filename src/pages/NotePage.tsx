import { useParams } from 'react-router-dom'

export default function NotePage() {
  const { noteSlug } = useParams<{ noteSlug: string }>()
  return <div>Note: {noteSlug}</div>
}
