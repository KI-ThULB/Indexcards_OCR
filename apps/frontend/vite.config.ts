import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

const host = '127.0.0.1'
const apiPort = Number(process.env.INDEXCARDS_API_PORT ?? 8000)
const devPort = Number(process.env.INDEXCARDS_DEV_PORT ?? 5173)
const target = `http://${host}:${apiPort}`

export default defineConfig(({ command, isPreview }) => {
  const local = command === 'serve' && !isPreview
  return {
    plugins: [
      react(),
      {
        name: 'indexcards-local-bind',
        configResolved(config) {
          if (local && (apiPort === devPort || ![apiPort, devPort].every(port =>
            Number.isInteger(port) && port >= 1 && port <= 65535))) {
            throw new Error('Local API and frontend ports must be distinct and between 1 and 65535')
          }
          if (local && (config.server.host !== host || config.server.port !== devPort)) {
            throw new Error(`Local dev requires ${host}:${devPort}`)
          }
        },
      },
    ],
    envDir: local ? false : path.resolve(__dirname, '../..'),
    envPrefix: local ? [] : 'VITE_',
    server: {
      host,
      port: devPort,
      strictPort: true,
      proxy: {
        '/api': { target, ws: true },
        '/batches-static': { target },
      },
    },
  }
})
