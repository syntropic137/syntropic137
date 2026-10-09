/**
 * Custom-element build of @syn137/skyline-svelte-v5 (Platforms: non-Svelte
 * hosts get <sky-*> elements). Run with `pnpm run build:ce`.
 *
 * Output: dist-ce/skyline-elements.js, one ES module with the Svelte runtime,
 * the wrapped components and their CSS bundled. Component CSS is injected at
 * mount into each element's shadow root. Themes are not bundled: the host
 * page links @syn137/skyline-themes. See examples/custom-elements.html.
 *
 * The landing elements have their own build, one module per element:
 * vite.elements.config.ts.
 */
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import { skylineCustomElements } from './vite.ce.shared'

export default defineConfig({
  plugins: [skylineCustomElements()],
  resolve: { conditions: ['browser'] },
  build: {
    outDir: 'dist-ce',
    emptyOutDir: true,
    target: 'es2022',
    sourcemap: true,
    lib: {
      entry: fileURLToPath(new URL('./src/custom-elements.ts', import.meta.url)),
      formats: ['es'],
      fileName: () => 'skyline-elements.js',
    },
  },
})
