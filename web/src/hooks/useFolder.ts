import { useQuery } from '@tanstack/react-query'
import { fetchFolder } from '../api/folders'

export function useFolder(slug: string) {
  return useQuery({
    queryKey: ['folder', slug],
    queryFn: () => fetchFolder(slug),
    enabled: !!slug,
  })
}
