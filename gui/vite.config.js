import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Gateway-only mode: all UI traffic must go through NoETL Gateway.
let gatewayUrl = process.env.VITE_GATEWAY_URL
if (!gatewayUrl) {
  gatewayUrl = "http://localhost:8090"
}
console.log("VITE_GATEWAY_URL=", gatewayUrl)

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
    // Keep legacy global for compatibility; points to gateway API base.
    __FASTAPI_URL__: JSON.stringify(`${gatewayUrl.replace(/\/+$/, "")}/api`)
  }
})
