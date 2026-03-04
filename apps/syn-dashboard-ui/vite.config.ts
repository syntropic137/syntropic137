import path from 'path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { readFileSync } from 'fs'

const { version } = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf-8')) as { version: string }

const uiFeedbackPath = path.resolve(__dirname, '../../lib/ui-feedback/packages/ui-feedback-react/src')

// Suppress noisy EPIPE/ECONNRESET proxy errors with a single-line log.
// These fire when the backend closes before Vite's proxy finishes relaying.
//
// Vite registers its own 'error' handler (which prints full stack traces) AFTER
// `configure` runs.  We use queueMicrotask to strip Vite's handlers once they
// exist, leaving only our concise handler.
function quietProxy(proxy: import('http-proxy').Server, label: string) {
  const handler = (err: Error, _req: unknown, res: unknown) => {
    const code = (err as NodeJS.ErrnoException).code
    if (code === 'EPIPE' || code === 'ECONNRESET' || code === 'ECONNREFUSED') {
      console.log(`\x1b[33m[proxy:${label}]\x1b[0m ${code} — backend closed or not running`)
    } else {
      console.error(`[proxy:${label}]`, err.message)
    }
    if (res && typeof res === 'object' && 'writeHead' in res && !(res as { headersSent: boolean }).headersSent) {
      (res as import('http').ServerResponse).writeHead(502).end()
    }
  }
  proxy.on('error', handler)
  // After Vite registers its verbose handlers, replace them all with ours
  queueMicrotask(() => {
    proxy.removeAllListeners('error')
    proxy.on('error', handler)
  })
  // Suppress socket-level errors on the proxied connection (prevents secondary stack traces)
  proxy.on('proxyReq', (proxyReq) => { proxyReq.on('error', () => {}) })
  proxy.on('proxyRes', (proxyRes) => { proxyRes.on('error', () => {}) })
  proxy.on('open', (proxySocket) => { proxySocket.on('error', () => {}) })
}

// https://vite.dev/config/
export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(version),
  },
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api/v1': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (p: string) => p.replace(/^\/api\/v1/, ''),  // Strip /api/v1/ — mirrors nginx behavior
        configure: (proxy) => quietProxy(proxy, 'api'),
      },
      // Only proxy our app WebSocket paths — avoid intercepting Vite's HMR socket
      '/ws/executions': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
        configure: (proxy) => quietProxy(proxy, 'ws'),
      },
      '/ws/activity': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
        configure: (proxy) => quietProxy(proxy, 'ws'),
      },
      '/ws/health': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        configure: (proxy) => quietProxy(proxy, 'ws'),
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
