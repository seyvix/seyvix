import { setupWorker } from 'msw/browser'
import { noteHandlers } from './handlers/notes'
import { folderHandlers } from './handlers/folders'

export const worker = setupWorker(...noteHandlers, ...folderHandlers)
