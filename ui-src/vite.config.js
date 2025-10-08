import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Derive API base URL from env with sensible default (prefers NoETL default 8083)
const apiUrl = process.env.VITE_API_BASE_URL || 'http://localhost:8083'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  server: {
    port: 3001,
  },
  define: {
    // Keep legacy global for existing code paths; populated from VITE_API_BASE_URL or default
    __FASTAPI_URL__: JSON.stringify(apiUrl)
  }
})
