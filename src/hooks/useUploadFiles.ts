import { useMutation } from '@tanstack/react-query'
import { startUploadJob } from '../api/notes'
import { useUploadContext } from '../contexts/UploadContext'

export function useUploadFiles() {
  const { addJob } = useUploadContext()

  return useMutation({
    mutationFn: ({ files, text }: { files: File[]; text?: string }) => startUploadJob(files, text),
    onSuccess: ({ jobId, noteId }) => {
      addJob({ jobId, noteId })
    },
  })
}
