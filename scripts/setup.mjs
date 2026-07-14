// scripts/setup.mjs
import { execSync, spawnSync } from 'child_process'
import { existsSync } from 'fs'
import { resolve } from 'path'

const ROOT = resolve(import.meta.dirname, '..')
const BACKEND = resolve(ROOT, 'apps/backend')

function run(cmd, opts = {}) {
  console.log(`  > ${cmd}`)
  execSync(cmd, { stdio: 'inherit', ...opts })
}

function checkCommand(cmd) {
  const result = spawnSync(cmd, ['--version'], { stdio: 'pipe' })
  return result.status === 0
}

console.log('\n=== Indexcards OCR - Project Setup ===\n')

// Step 1: Check uv is installed
console.log('1. Checking uv (Python manager)...')
if (!checkCommand('uv')) {
  console.error('\x1b[31muv is not installed.\x1b[0m')
  console.error('Install it from: https://docs.astral.sh/uv/getting-started/installation/')
  console.error('  curl -LsSf https://astral.sh/uv/install.sh | sh')
  process.exit(1)
}
console.log('   uv found.\n')

// Step 2: Create Python venv and install deps
console.log('2. Setting up Python backend...')
if (!existsSync(resolve(BACKEND, '.venv'))) {
  console.log('   Creating virtual environment...')
  run('uv venv', { cwd: BACKEND })
} else {
  console.log('   Virtual environment already exists.')
}

console.log('   Installing Python dependencies...')
run('uv pip install -r requirements.txt', { cwd: BACKEND })

if (existsSync(resolve(BACKEND, 'requirements-dev.txt'))) {
  console.log('   Installing Python dev dependencies...')
  run('uv pip install -r requirements-dev.txt', { cwd: BACKEND })
}
console.log('')

// Step 3: Install npm workspaces
console.log('3. Installing npm workspace dependencies...')
run('npm install', { cwd: ROOT })
console.log('')

// Step 4: Verify .env exists
console.log('4. Checking .env file...')
if (!existsSync(resolve(ROOT, '.env'))) {
  console.warn('\x1b[33mWARNING: No .env file found at project root.\x1b[0m')
  console.warn('Copy .env.example to .env and fill in your OPENROUTER_API_KEY:')
  console.warn('  cp .env.example .env')
} else {
  console.log('   .env file found.')
}

console.log('\n=== Setup complete! ===')
console.log('')
console.log('Available commands:')
console.log('  npm run dev        - Start frontend + backend')
console.log('  npm run build      - Build frontend + lint/typecheck backend')
console.log('  npm run test       - Run all tests')
console.log('  npm run lint       - Lint all packages')
console.log('  npm run typecheck  - Typecheck all packages')
console.log('  npm run format     - Format all packages')
console.log('')
