import { setupWorker } from 'msw/browser'
import { noteHandlers } from './handlers/notes'
import { folderHandlers } from './handlers/folders'
import { authHandlers } from './handlers/auth'

export const worker = setupWorker(...noteHandlers, ...folderHandlers, ...authHandlers)
