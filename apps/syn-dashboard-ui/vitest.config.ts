/// <reference types="vitest" />
import { readFileSync } from 'fs'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

const { version } = JSON.parse(
  readFileSync(new URL('./package.json', import.meta.url), 'utf-8'),
) as { version: string }

export default defineConfig({
  // Mirrors vite.config.ts. Without it, any test that renders a component
  // reading __APP_VERSION__ (Layout, the feedback widget mount) dies with a
  // ReferenceError rather than failing on what it set out to assert.
  define: {
    __APP_VERSION__: JSON.stringify(version),
  },
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
