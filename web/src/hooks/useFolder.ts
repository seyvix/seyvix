import { useQuery } from '@tanstack/react-query'
import { fetchFolder } from '../api/folders'

export function useFolder(path: string) {
  return useQuery({
    queryKey: ['category', path],
    queryFn: () => fetchFolder(path),
    enabled: !!path,
  })
}
