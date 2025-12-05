import path from 'path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const uiFeedbackPath = path.resolve(__dirname, '../../lib/ui-feedback/packages/ui-feedback-react/src')

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
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
      '@aef/ui-feedback-react': uiFeedbackPath,
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
