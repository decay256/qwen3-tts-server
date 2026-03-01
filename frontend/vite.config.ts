import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Sprint 5: dev proxy — forwards /api and /auth requests to FastAPI backend.
    // Without this, dev-server (port 5173) returns 405 for POST requests.
    // Root cause: Vite's dev server only handles static assets (GET);
    // API calls must be proxied to the backend (port 8080).
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/auth': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
})
