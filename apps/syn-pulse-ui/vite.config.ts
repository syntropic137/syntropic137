import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  // VITE_BASE_PATH is set during gateway Docker build to '/pulse/'
  base: process.env.VITE_BASE_PATH || '/',
  plugins: [react(), tailwindcss()],
  server: {
    port: 5174,
    proxy: {
      '/api/v1': {
        target: 'http://localhost:9137',
        changeOrigin: true,
        rewrite: (p: string) => p.replace(/^\/api\/v1/, ''),
      },
    },
  },
})
