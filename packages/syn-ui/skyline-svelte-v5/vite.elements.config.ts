/**
 * Elements build for the landing page and other non-Svelte apps in the
 * workspace: `pnpm run build:elements` writes dist-elements/, one ES module
 * per <sky-*> element plus one shared chunk (the Svelte runtime, the
 * shadow-root helpers and every module more than one element uses), then
 * scripts/elements-size.mjs checks the 45 KB gzip budget.
 *
 *   dist-elements/s-mark.js, iso-city.js, eval-explorer.js, harness-chip.js,
 *   harness-lanes.js, tool-log.js, usage-band.js   one per element
 *   dist-elements/index.js                         all seven
 *   dist-elements/chunks/runtime.js                the shared chunk
 *
 * package.json maps `@syn137/skyline-svelte-v5/elements/<name>` and
 * `/elements` onto these files. Minified, ES2022, no source maps (the
 * consumer's bundler re-bundles them). Themes are not bundled: the page
 * loads @syn137/skyline-themes and the tokens inherit into each shadow root.
 */
import { readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { defineConfig, type Rollup } from 'vite'
import { skylineCustomElements } from './vite.ce.shared'

const dir = fileURLToPath(new URL('./src/elements/', import.meta.url))
const ENTRY = /^(?!register|types)[a-z-]+\.ts$/
const input = Object.fromEntries(readdirSync(dir).filter((f) => ENTRY.test(f)).map((f) => [f.replace(/\.ts$/, ''), `${dir}${f}`]))
const elementEntries = new Set(Object.entries(input).filter(([name]) => name !== 'index').map(([, file]) => file))

/** The element entries that reach `id` through static imports (index.js does not count). */
function entriesOf(id: string, getModuleInfo: Rollup.GetModuleInfo, seen = new Set<string>()): Set<string> {
  const out = new Set<string>()
  if (seen.has(id)) return out
  seen.add(id)
  if (elementEntries.has(id)) out.add(id)
  for (const parent of getModuleInfo(id)?.importers ?? []) for (const e of entriesOf(parent, getModuleInfo, seen)) out.add(e)
  return out
}

export default defineConfig({
  plugins: [skylineCustomElements()],
  // 'production' lets esm-env (Svelte's DEV flag) resolve statically, so dev-only code drops out.
  resolve: { conditions: ['module', 'browser', 'production'] },
  define: { 'process.env.NODE_ENV': JSON.stringify('production') },
  build: {
    outDir: 'dist-elements',
    emptyOutDir: true,
    target: 'es2022',
    minify: 'esbuild',
    sourcemap: false,
    modulePreload: false,
    rollupOptions: {
      input,
      preserveEntrySignatures: 'exports-only',
      output: {
        format: 'es',
        entryFileNames: '[name].js',
        chunkFileNames: 'chunks/[name].js',
        // Everything two or more elements share goes in one chunk, so a page
        // loads the Svelte runtime once whichever elements it imports.
        manualChunks(id, { getModuleInfo }) {
          if (elementEntries.has(id)) return undefined
          return entriesOf(id, getModuleInfo).size > 1 ? 'runtime' : undefined
        },
      },
    },
  },
})
