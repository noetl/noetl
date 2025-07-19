import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  server: {
    port: 3000,
    proxy: {
      '/api': 'http://localhost:8081',
      '/health': 'http://localhost:8081',
    }
  },
  define: {
    __FASTAPI_URL__: JSON.stringify('http://localhost:8081')
  }
})
