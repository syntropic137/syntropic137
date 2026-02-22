import path from 'path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { readFileSync } from 'fs'

const { version } = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf-8')) as { version: string }

const uiFeedbackPath = path.resolve(__dirname, '../../lib/ui-feedback/packages/ui-feedback-react/src')

// https://vite.dev/config/
export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(version),
  },
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true,  // Enable WebSocket proxy
        configure: (proxy) => {
          proxy.on('error', () => { /* suppress backend-not-running noise */ })
        },
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('error', () => { /* suppress backend-not-running noise */ })
        },
      },
    },
    fs: {
      // Allow serving files from the ui-feedback package
      allow: ['.', uiFeedbackPath, path.resolve(__dirname, '../../lib/ui-feedback')],
    },
  },
  resolve: {
    alias: {
      // Resolve the linked ui-feedback-react package
      '@syn137/ui-feedback-react': uiFeedbackPath,
    },
    // Dedupe these packages to use the dashboard's node_modules
    dedupe: ['react', 'react-dom', 'html2canvas', 'clsx'],
  },
  optimizeDeps: {
    // Include linked package dependencies for pre-bundling
    include: ['html2canvas', 'clsx'],
    // Force Vite to treat files from this directory as source
    entries: [
      'src/**/*.{ts,tsx}',
      `${uiFeedbackPath}/**/*.{ts,tsx}`,
    ],
  },
})
