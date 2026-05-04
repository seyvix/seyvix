import { Navigate, useParams } from 'react-router-dom'

export default function FolderPage() {
  const { '*': categoryPath } = useParams()
  return <Navigate to={`/categories/${categoryPath ?? ''}`} replace />
}
