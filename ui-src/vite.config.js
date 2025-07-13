// ui-src/vite.config.js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

export default defineConfig({
  plugins: [react()],
  root: resolve(__dirname, 'templates'),
  build: {
    outDir: resolve(__dirname, 'dist'),
    emptyOutDir: true,
    // Disable asset hashing to ensure consistent filenames
    assetsDir: 'assets',
    rollupOptions: {
      input: {
        // Define all three of your pages
        main: resolve(__dirname, 'templates/index.html'),
        editor: resolve(__dirname, 'templates/editor.html'),
        execution: resolve(__dirname, 'templates/execution.html'),
        catalog: resolve(__dirname, 'templates/catalog.html'), // <-- ADD THIS LINE
      },
      output: {
        // Disable hashing in filenames
        entryFileNames: 'assets/[name].js',
        chunkFileNames: 'assets/[name].js',
        assetFileNames: 'assets/[name].[ext]'
      }
    }
  },
  resolve: {
    alias: {
      '/src': resolve(__dirname, 'src'),
      // The '/static' alias is no longer needed since all JS is in /src
    }
  }
})
