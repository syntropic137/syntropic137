import { readFileSync } from 'node:fs'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import { defineConfig } from 'vitest/config'

// Same backend as apps/syn-dashboard-ui: /api/v1/* is proxied to the API with
// the prefix stripped (SSE included, under /api/v1/sse/*).
const API_TARGET = process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:9137'
// Optional Basic Auth for a remote gateway (e.g. the VPS over Tailscale). Set
// SYN_UI_PROXY_AUTH to "user:password". Deliberately NOT a VITE_-prefixed name:
// Vite exposes every VITE_* variable to the client bundle via import.meta.env, so
// a credential under that prefix would ship to the browser. This one is read
// server-side only and applied to proxied requests.
const API_AUTH = process.env.SYN_UI_PROXY_AUTH
// Kept out of the resolved config object: Vite serialises `server.proxy` (DEBUG=vite:*
// prints it), so the header is injected per request in `configure` instead.
const API_AUTH_HEADER = API_AUTH ? `Basic ${Buffer.from(API_AUTH).toString('base64')}` : undefined

// The app is served at /next until it takes over / (spec, Migration plan).
// Set SYN_UI_BASE=/next/ for that build; the router reads import.meta.env.BASE_URL.
const BASE = process.env.SYN_UI_BASE ?? '/'

// The bundle's own release, for the shell's "ui" beside the API's version (shell/build.svelte.ts).
// The product version always comes from the API (getBuildInfo), never from here.
const { version: UI_VERSION } = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf-8')) as { version: string }

export default defineConfig({
  base: BASE,
  plugins: [svelte()],
  define: { __SYN_UI_VERSION__: JSON.stringify(UI_VERSION) },
  // Tests run the binding's runes ($effect) on Svelte's client runtime, not the SSR one.
  ...(process.env.VITEST ? { resolve: { conditions: ['browser'] } } : {}),
  server: {
    port: 5174,
    proxy: {
      '/api/v1': {
        target: API_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/v1/, ''),
        configure: (proxy) => {
          if (API_AUTH_HEADER) proxy.on('proxyReq', (req) => req.setHeader('authorization', API_AUTH_HEADER))
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
