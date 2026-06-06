const IWORK_EXTENSIONS = ['.key', '.pages', '.numbers'] as const

const IWORK_HINT =
  'Файлы Apple Keynote / Pages / Numbers пока не поддерживаются. ' +
  'Экспортируй из приложения в PDF и загрузи снова.'

export interface FileRejection {
  file: File
  reason: string
}

export interface PartitionedFiles {
  accepted: File[]
  rejected: FileRejection[]
}

function unsupportedReason(file: File): string | null {
  const name = file.name.toLowerCase()
  for (const ext of IWORK_EXTENSIONS) {
    if (name.endsWith(ext)) return IWORK_HINT
  }
  return null
}

export function partitionUploadFiles(files: File[]): PartitionedFiles {
  const accepted: File[] = []
  const rejected: FileRejection[] = []
  for (const file of files) {
    const reason = unsupportedReason(file)
    if (reason) rejected.push({ file, reason })
    else accepted.push(file)
  }
  return { accepted, rejected }
}
