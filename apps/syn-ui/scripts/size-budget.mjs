#!/usr/bin/env node
// Size budget (spec, Architecture): under 100 KB of gzip-compressed JavaScript
// on first load. First load = the entry chunk plus every chunk it imports
// statically (what the browser fetches before the first page renders, minus
// that page's own lazy chunk). Route chunks are reported, and the largest
// route's first visit (entry + its chunk) is checked against the same budget.
//
// Reads dist/.vite/manifest.json (build.manifest in vite.config.ts).
// Env: SIZE_BUDGET_KB (default 100).
import { readFileSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { gzipSync } from 'node:zlib'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const dist = join(root, 'dist')
const manifestPath = join(dist, '.vite', 'manifest.json')
const budgetKb = Number(process.env.SIZE_BUDGET_KB ?? 100)

if (!existsSync(manifestPath)) {
  console.error(`size-budget: ${manifestPath} not found; run vite build first`)
  process.exit(2)
}
const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
const gz = new Map()
const gzipSize = (file) => {
  if (!gz.has(file)) gz.set(file, gzipSync(readFileSync(join(dist, file)), { level: 9 }).length)
  return gz.get(file)
}
const kb = (n) => `${(n / 1024).toFixed(1)} KB`

/** Every JS file a manifest key pulls in statically, itself included. */
function closure(key, seen = new Set()) {
  const chunk = manifest[key]
  if (!chunk || seen.has(chunk.file)) return seen
  seen.add(chunk.file)
  for (const dep of chunk.imports ?? []) closure(dep, seen)
  return seen
}
const sum = (files) => [...files].filter((f) => f.endsWith('.js')).reduce((n, f) => n + gzipSize(f), 0)

const entryKey = Object.keys(manifest).find((k) => manifest[k].isEntry)
if (!entryKey) {
  console.error('size-budget: no entry chunk in manifest')
  process.exit(2)
}
const first = closure(entryKey)
const firstLoad = sum(first)
const css = (manifest[entryKey].css ?? []).reduce((n, f) => n + gzipSize(f), 0)

const routes = Object.entries(manifest)
  .filter(([k, c]) => c.isDynamicEntry && k.includes('/routes/'))
  .map(([k]) => {
    const extra = [...closure(k)].filter((f) => !first.has(f))
    return { route: k.replace(/^.*\/routes\//, ''), size: sum(extra) }
  })
  .sort((a, b) => b.size - a.size)

const budget = budgetKb * 1024
console.log(`\nFirst-load JS (gzip): ${kb(firstLoad)} of ${budgetKb} KB budget   [${[...first].filter((f) => f.endsWith('.js')).length} file(s)]`)
console.log(`First-load CSS (gzip): ${kb(css)}`)
console.log('Route chunks (gzip, beyond first load):')
for (const r of routes) console.log(`  ${r.route.padEnd(28)} ${kb(r.size).padStart(9)}   first visit ${kb(firstLoad + r.size)}`)

const worst = routes[0]
let failed = false
if (firstLoad > budget) {
  console.error(`\nFAIL: first-load JS ${kb(firstLoad)} exceeds ${budgetKb} KB`)
  failed = true
}
if (worst && firstLoad + worst.size > budget) {
  console.error(`\nFAIL: first visit to ${worst.route} needs ${kb(firstLoad + worst.size)}, over ${budgetKb} KB`)
  failed = true
}
if (failed) process.exit(1)
console.log('\nsize budget ok')
