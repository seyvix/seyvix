import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const appRoot = path.dirname(fileURLToPath(import.meta.url))
const serverBuild = path.join(appRoot, 'build/server/index.js')
const serveBin = path.join(appRoot, 'node_modules/.bin/react-router-serve')

const child = spawn(serveBin, [serverBuild], {
  env: process.env,
  stdio: 'inherit',
})

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal)
    return
  }

  process.exit(code ?? 1)
})
