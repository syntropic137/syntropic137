import { resolve } from 'path';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
const which = process.env.WHICH!;
export default defineConfig({
  root: __dirname, base: './', plugins: [react()],
  resolve: { alias: { WIDGET: which === 'before' ? resolve(__dirname, 'main/index.ts') : resolve(__dirname, '../src/index.ts') } },
  build: { outDir: resolve(__dirname, `dist-${which}`), emptyOutDir: true },
});
