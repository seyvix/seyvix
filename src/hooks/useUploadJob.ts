import { useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchUploadJob } from '../api/notes'
import { useUploadContext } from '../contexts/UploadContext'

export function useUploadJob(jobId: string) {
  const queryClient = useQueryClient()
  const { removeJob } = useUploadContext()

  const query = useQuery({
    queryKey: ['upload-job', jobId],
    queryFn: () => fetchUploadJob(jobId),
    refetchInterval: (query) => {
      if (query.state.data?.status === 'done') return false
      return 300
    },
  })

  useEffect(() => {
    if (query.data?.status === 'done') {
      // Инвалидируем список заметок и убираем джоб через секунду (чтобы toast успел показать "готово")
      queryClient.invalidateQueries({ queryKey: ['notes'] })
      const t = setTimeout(() => removeJob(jobId), 2000)
      return () => clearTimeout(t)
    }
  }, [query.data?.status, jobId, queryClient, removeJob])

  return query
}
