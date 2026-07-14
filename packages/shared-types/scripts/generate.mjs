// packages/shared-types/scripts/generate.mjs
//
// Reads all .schema.json files from schemas/ and generates:
//   - generated/ts/index.ts  (TypeScript interfaces)
//   - generated/py/          (Pydantic models, if datamodel-codegen available)
//
// Uses a custom JSON Schema → TypeScript converter instead of json-schema-to-typescript
// to produce clean, duplicate-free output with inline types (no helper aliases).

import { readFileSync, writeFileSync, mkdirSync, readdirSync } from 'fs'
import { resolve, basename } from 'path'
import { execSync } from 'child_process'
import { fileURLToPath } from 'url'
import { dirname } from 'path'

const __dirname = dirname(fileURLToPath(import.meta.url))

const ROOT = resolve(__dirname, '..')
const SCHEMAS_DIR = resolve(ROOT, 'schemas')
const TS_OUT = resolve(ROOT, 'generated', 'ts')
const PY_OUT = resolve(ROOT, 'generated', 'py')

// Ensure output dirs
mkdirSync(TS_OUT, { recursive: true })
mkdirSync(PY_OUT, { recursive: true })

const schemaFiles = readdirSync(SCHEMAS_DIR).filter(f => f.endsWith('.schema.json')).sort()

if (schemaFiles.length === 0) {
  console.error('No .schema.json files found in schemas/')
  process.exit(1)
}

console.log(`Generating types from ${schemaFiles.length} schema files...\n`)

/**
 * Convert a JSON Schema property type to a TypeScript type string.
 * Handles: string, number, integer, boolean, array, object, null,
 *          anyOf (unions), $ref (references to definitions).
 */
function jsonSchemaTypeToTs(prop, allDefinitions, indent = '') {
  if (!prop) return 'unknown'

  // $ref: #/definitions/Foo → reference the interface name
  if (prop.$ref) {
    const refName = prop.$ref.split('/').pop()
    return refName
  }

  // anyOf: union type
  if (prop.anyOf) {
    const types = prop.anyOf.map(p => jsonSchemaTypeToTs(p, allDefinitions, indent))
    // Deduplicate (e.g. null | null)
    const unique = [...new Set(types)]
    return unique.join(' | ')
  }

  // Array
  if (prop.type === 'array') {
    const itemType = prop.items ? jsonSchemaTypeToTs(prop.items, allDefinitions, indent) : 'unknown'
    return `${itemType}[]`
  }

  // Object with additionalProperties (dict/map)
  if (prop.type === 'object' && prop.additionalProperties) {
    const valueType = jsonSchemaTypeToTs(prop.additionalProperties, allDefinitions, indent)
    return `{ [k: string]: ${valueType} }`
  }

  // Enum constraint on string type: produce a TypeScript union of string literals
  if (prop.type === 'string' && Array.isArray(prop.enum)) {
    return prop.enum.map(v => `'${v}'`).join(' | ')
  }

  // Primitives
  switch (prop.type) {
    case 'string': return 'string'
    case 'number':
    case 'integer': return 'number'
    case 'boolean': return 'boolean'
    case 'null': return 'null'
    case 'object': return '{ [k: string]: unknown }'
    default: return 'unknown'
  }
}

/**
 * Generate a TypeScript interface for a JSON Schema object definition.
 */
function generateInterface(name, defSchema, requiredFields, allDefinitions) {
  const lines = [`export interface ${name} {`]
  const properties = defSchema.properties || {}
  const required = new Set(requiredFields || defSchema.required || [])

  for (const [fieldName, fieldSchema] of Object.entries(properties)) {
    const isRequired = required.has(fieldName)
    const tsType = jsonSchemaTypeToTs(fieldSchema, allDefinitions)
    const optional = isRequired ? '' : '?'
    // For optional fields that include null in their type, omit the explicit null
    // since TypeScript's optional (?:) already allows undefined.
    // Keep null if it's part of the union (e.g. field can be null or string).
    lines.push(`  ${fieldName}${optional}: ${tsType}`)
  }

  lines.push('}')
  return lines.join('\n')
}

// --- Merge all definitions into one combined map ---
const allDefinitions = {}
const orderedNames = []

for (const file of schemaFiles) {
  const schemaPath = resolve(SCHEMAS_DIR, file)
  const schema = JSON.parse(readFileSync(schemaPath, 'utf8'))
  const definitions = schema.definitions || {}

  for (const [name, defSchema] of Object.entries(definitions)) {
    if (allDefinitions[name]) {
      console.log(`  Skipping duplicate: ${name}`)
      continue
    }
    allDefinitions[name] = defSchema
    orderedNames.push(name)
    console.log(`  Collected: ${name}`)
  }
}

// --- Generate TypeScript interfaces ---
const tsInterfaces = []

for (const name of orderedNames) {
  const defSchema = allDefinitions[name]
  const iface = generateInterface(name, defSchema, defSchema.required, allDefinitions)
  tsInterfaces.push(iface)
  console.log(`  TS: ${name}`)
}

const tsHeader = [
  '// AUTO-GENERATED from JSON Schema — do not edit manually',
  '// Regenerate with: turbo generate (or npm run generate in packages/shared-types)',
  '',
].join('\n')

const tsContent = tsHeader + tsInterfaces.join('\n\n') + '\n'
writeFileSync(resolve(TS_OUT, 'index.ts'), tsContent)
console.log(`\n  Written: generated/ts/index.ts (${tsInterfaces.length} interfaces)`)

// --- Pydantic Generation (optional, requires datamodel-code-generator) ---
try {
  // Check if datamodel-codegen is available
  execSync('uv run datamodel-codegen --version', { stdio: 'pipe', cwd: resolve(ROOT, '..', '..', 'apps', 'backend') })

  for (const file of schemaFiles) {
    const schemaPath = resolve(SCHEMAS_DIR, file)
    const groupName = basename(file, '.schema.json')
    const pyOutFile = resolve(PY_OUT, `${groupName}.py`)

    try {
      execSync(
        `uv run datamodel-codegen --input "${schemaPath}" --output "${pyOutFile}" --output-model-type pydantic_v2.BaseModel --target-python-version 3.12`,
        { stdio: 'pipe', cwd: resolve(ROOT, '..', '..', 'apps', 'backend') }
      )
      console.log(`  PY: ${groupName}.py`)
    } catch (err) {
      console.error(`  ERROR generating Pydantic for ${groupName}: ${err.stderr?.toString() || err.message}`)
    }
  }

  // Create __init__.py
  const pyModules = schemaFiles.map(f => basename(f, '.schema.json'))
  const pyInit = `# AUTO-GENERATED — do not edit manually\n` +
    pyModules.map(m => `from .${m} import *`).join('\n') + '\n'
  writeFileSync(resolve(PY_OUT, '__init__.py'), pyInit)
  console.log(`  Written: generated/py/__init__.py`)
} catch {
  console.log('\n  Skipping Pydantic generation (datamodel-codegen not available)')
  console.log('  Install it: pip install datamodel-code-generator')
}

console.log('\nGeneration complete.')
