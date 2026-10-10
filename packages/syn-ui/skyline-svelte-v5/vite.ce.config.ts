/**
 * Custom-element build of @syn137/skyline-svelte-v5 (Platforms: non-Svelte
 * hosts get <sky-*> elements). Run with `pnpm run build:ce`.
 *
 * Output: dist-ce/skyline-elements.js, one ES module with the Svelte runtime,
 * the wrapped components and their CSS bundled. Component CSS is injected at
 * mount into each element's shadow root. Themes are not bundled: the host
 * page links @syn137/skyline-themes. See examples/custom-elements.html.
 *
 * Only this build compiles the wrappers in src/custom-elements/ as custom
 * elements; svelte.config.js (app, tests, svelte-check) is untouched.
 */
import { basename } from 'node:path'
import { fileURLToPath } from 'node:url'
import { svelte, vitePreprocess } from '@sveltejs/vite-plugin-svelte'
import type { PreprocessorGroup } from 'svelte/compiler'
import { defineConfig } from 'vite'
import { CUSTOM_ELEMENT_OPTIONS } from './src/custom-elements/options'

const CE_WRAPPER = /[\\/]src[\\/]custom-elements[\\/][^\\/]+\.svelte$/

/** Object literal with bare keys: Svelte only reads `customElement` written that way. */
function literal(value: unknown): string {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return `{ ${Object.entries(value).map(([k, v]) => `${k}: ${literal(v)}`).join(', ')} }`
  }
  return JSON.stringify(value)
}

/** Prepends <svelte:options customElement={...}> from options.ts to each wrapper. */
const customElementOptions: PreprocessorGroup = {
  name: 'skyline-custom-element-options',
  markup({ content, filename }) {
    if (!filename || !CE_WRAPPER.test(filename)) return
    const options = CUSTOM_ELEMENT_OPTIONS[basename(filename)]
    if (!options) throw new Error(`No custom-element options for ${filename} in src/custom-elements/options.ts`)
    return { code: `<svelte:options customElement={${literal(options)}} />${content}` }
  },
}

export default defineConfig({
  plugins: [
    svelte({
      configFile: false,
      preprocess: [customElementOptions, vitePreprocess()],
      emitCss: false,
      compilerOptions: { runes: true, css: 'injected' },
      dynamicCompileOptions: ({ filename }) => (CE_WRAPPER.test(filename) ? { customElement: true } : undefined),
    }),
  ],
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
