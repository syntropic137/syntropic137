import { svelte } from '@sveltejs/vite-plugin-svelte'
import { defineConfig } from 'vitest/config'

// Component tests run in Node by default. A test that needs a DOM adds
// `// @vitest-environment jsdom` at the top (jsdom is not a dependency yet:
// add it with @testing-library/svelte when the first component test lands).
export default defineConfig({
  plugins: [svelte()],
  resolve: { conditions: ['browser'] },
  test: {
    include: ['src/**/*.test.ts'],
  },
})
