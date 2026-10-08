import { svelte } from '@sveltejs/vite-plugin-svelte'
import { defineConfig } from 'vitest/config'

// Same backend as apps/syn-dashboard-ui: /api/v1/* is proxied to the API with
// the prefix stripped (SSE included, under /api/v1/sse/*).
const API_TARGET = process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:9137'

// The app is served at /next until it takes over / (spec, Migration plan).
// Set SYN_UI_BASE=/next/ for that build; the router reads import.meta.env.BASE_URL.
const BASE = process.env.SYN_UI_BASE ?? '/'

export default defineConfig({
  base: BASE,
  plugins: [svelte()],
  server: {
    port: 5174,
    proxy: {
      '/api/v1': {
        target: API_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/v1/, ''),
        configure: (proxy) => {
          proxy.on('error', (err: NodeJS.ErrnoException) => {
            console.log(`\x1b[33m[proxy:api]\x1b[0m ${err.code ?? err.message} (is the API running on ${API_TARGET}? or use pnpm dev:fixtures)`)
          })
        },
      },
    },
  },
  build: {
    target: 'es2022',
    // scripts/size-budget.mjs reads the manifest to find the first-load chunks.
    manifest: true,
    cssCodeSplit: true,
    sourcemap: false,
  },
  test: {
    include: ['src/**/*.test.ts'],
    environment: 'node',
  },
})
