import { Navigate, useParams } from 'react-router'

export default function FolderPage() {
  const { '*': categoryPath } = useParams()
  return <Navigate to={`/categories/${categoryPath ?? ''}`} replace />
}
