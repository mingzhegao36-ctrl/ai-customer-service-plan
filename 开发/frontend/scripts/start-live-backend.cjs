const { spawn } = require('node:child_process')
const path = require('node:path')

const backend = path.resolve(__dirname, '../../backend')
const python = process.platform === 'win32'
  ? path.join(backend, '.venv', 'Scripts', 'python.exe')
  : path.join(backend, '.venv', 'bin', 'python')
const child = spawn(python, ['-m', 'uvicorn', 'app.main:app', '--app-dir', backend, '--host', '127.0.0.1', '--port', '8001'], {
  cwd: process.cwd(),
  env: process.env,
  stdio: 'inherit',
})
const stop = signal => { if (!child.killed) child.kill(signal) }
process.on('SIGINT', () => stop('SIGINT'))
process.on('SIGTERM', () => stop('SIGTERM'))
child.on('exit', code => process.exit(code ?? 0))
