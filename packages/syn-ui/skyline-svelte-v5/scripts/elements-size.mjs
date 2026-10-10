#!/usr/bin/env node
// Elements budget (landing plan, section 4c): the whole <sky-*> elements
// payload, every element module plus the shared runtime chunk, must stay
// under 45 KB of gzip-compressed JavaScript. That is what a page using all
// seven elements downloads. index.js only re-exports the elements, so it is
// listed but not counted twice.
//
// Reads dist-elements/ (run `vite build --config vite.elements.config.ts`
// first; `pnpm run build:elements` does both). Env: ELEMENTS_BUDGET_KB
// (default 45).
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { gzipSync } from 'node:zlib'

const dist = join(dirname(fileURLToPath(import.meta.url)), '..', 'dist-elements')
const budgetKb = Number(process.env.ELEMENTS_BUDGET_KB ?? 45)

if (!existsSync(dist)) {
  console.error(`elements-size: ${dist} not found; run the elements build first`)
  process.exit(2)
}
const files = []
const walk = (d) => {
  for (const name of readdirSync(d)) {
    const p = join(d, name)
    if (statSync(p).isDirectory()) walk(p)
    else if (name.endsWith('.js')) files.push(p)
  }
}
walk(dist)
const kb = (n) => `${(n / 1024).toFixed(1)} KB`
const rows = files
  .map((f) => {
    const buf = readFileSync(f)
    return { file: relative(dist, f), raw: buf.length, gz: gzipSync(buf, { level: 9 }).length }
  })
  .sort((a, b) => b.gz - a.gz)
const counted = rows.filter((r) => r.file !== 'index.js')
const total = counted.reduce((n, r) => n + r.gz, 0)
const raw = counted.reduce((n, r) => n + r.raw, 0)
for (const r of rows) console.log(`${r.file.padEnd(28)} ${kb(r.raw).padStart(10)} ${kb(r.gz).padStart(10) } gzip${r.file === 'index.js' ? '  (re-exports, not counted)' : ''}`)
console.log(`${'all elements + runtime'.padEnd(28)} ${kb(raw).padStart(10)} ${kb(total).padStart(10)} gzip  (budget ${budgetKb} KB)`)
if (!files.some((f) => relative(dist, f) === join('chunks', 'runtime.js'))) {
  console.error('elements-size: no shared chunks/runtime.js; the elements must share one Svelte runtime chunk')
  process.exit(1)
}
if (total > budgetKb * 1024) {
  console.error(`elements-size: ${kb(total)} gzip is over the ${budgetKb} KB budget`)
  process.exit(1)
}
console.log('elements-size ok')
