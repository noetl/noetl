import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    sourcemap: true,
  },
  server: {
    port: 3000,
    proxy: {
      "/api": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
  define: {
    // in __API_BASE_URL__ need put noetl api base url backend
    __API_BASE_URL__: JSON.stringify("http://localhost:8080/api"), // for local development
    __FASTAPI_URL__: JSON.stringify("http://localhost:8000"),
  },
});
