import { vitePreprocess } from '@sveltejs/vite-plugin-svelte'

/** @type {import('svelte/compiler').CompileOptions & { preprocess: unknown }} */
export default {
  preprocess: vitePreprocess(),
  compilerOptions: { runes: true },
}
