import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { viteSingleFile } from 'vite-plugin-singlefile'
import path from 'node:path'

// Auth-stripped, local-only scaffold (no @base44/vite-plugin).
// Domain data comes from the repo's FastAPI at VITE_API_BASE (default :8000).
// VITE_OFFLINE=1 produces a single self-contained index.html (data baked in) that
// opens directly via file:// — see `npm run build:export`.
// https://vite.dev/config/
const offline = process.env.VITE_OFFLINE === '1'

export default defineConfig({
  logLevel: 'error',
  base: offline ? './' : '/',
  plugins: [react(), ...(offline ? [viteSingleFile()] : [])],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  build: offline ? { outDir: 'export-standalone' } : {},
  server: {
    port: 5173, // must match the backend CORS allow_origins
  },
})
