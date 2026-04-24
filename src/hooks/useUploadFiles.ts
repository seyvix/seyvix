import { useMutation, useQueryClient } from '@tanstack/react-query'
import { uploadFiles } from '../api/notes'

export function useUploadFiles() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (files: File[]) => uploadFiles(files),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notes'] })
    },
  })
}
