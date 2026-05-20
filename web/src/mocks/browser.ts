import { setupWorker } from 'msw/browser'
import { authHandlers } from './handlers/auth'
import { noteHandlers } from './handlers/notes'
import { folderHandlers } from './handlers/folders'

export const worker = setupWorker(...authHandlers, ...noteHandlers, ...folderHandlers)
