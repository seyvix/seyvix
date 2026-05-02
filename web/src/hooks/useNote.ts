import { useQuery } from '@tanstack/react-query'
import { fetchNote } from '../api/notes'

export function useNote(slug: string) {
  return useQuery({
    queryKey: ['note', slug],
    queryFn: () => fetchNote(slug),
    enabled: !!slug,
  })
}
