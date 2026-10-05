import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// The browser only talks to this dev server. Requests to /api are forwarded to the FastAPI
// container, so the frontend and API share one origin: no CORS, and the browser never needs
// to reach MinIO or know Docker hostnames (trap #10).
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': process.env.API_PROXY_TARGET ?? 'http://localhost:8000',
    },
    // File change events don't always cross Docker Desktop bind mounts; poll when asked to.
    watch: { usePolling: process.env.VITE_USE_POLLING === 'true' },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
})
