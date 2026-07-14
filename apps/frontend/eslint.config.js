import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    rules: {
      '@typescript-eslint/no-unused-vars': ['error', {
        argsIgnorePattern: '^_',
        varsIgnorePattern: '^_',
        destructuredArrayIgnorePattern: '^_',
      }],
      // eslint-plugin-react-hooks v7 ships React Compiler-era rules that flag
      // legitimate reset/clamp-on-prop-change effects and a non-component helper
      // export. Kept advisory (warn) to avoid refactoring working code; revisit
      // when/if the React Compiler is adopted.
      'react-hooks/set-state-in-effect': 'warn',
      'react-refresh/only-export-components': 'warn',
    },
  },
])
