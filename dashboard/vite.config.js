import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'
import { inlineSingleFile } from './src/vite-plugins/inline-single-file.js'
import path from 'node:path'

// Auth-stripped, local-only scaffold.
// Domain data comes from the repo's FastAPI at VITE_API_BASE (default :8000).
// VITE_OFFLINE=1 produces a single self-contained index.html (data baked in) that
// opens directly via file:// — see `npm run build:export`.
// https://vite.dev/config/
const offline = process.env.VITE_OFFLINE === '1'

export default defineConfig({
  logLevel: 'error',
  base: offline ? './' : '/',
  plugins: [react(), tailwindcss(), ...(offline ? [inlineSingleFile()] : [])],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  build: offline ? { outDir: 'export-standalone' } : {},
  server: {
    port: 5173, // must match the backend CORS allow_origins
  },
})
