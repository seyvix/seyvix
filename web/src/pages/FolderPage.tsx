import { useParams } from 'react-router-dom'

export default function FolderPage() {
  const { folderSlug } = useParams<{ folderSlug: string }>()
  return <div>Folder: {folderSlug}</div>
}
