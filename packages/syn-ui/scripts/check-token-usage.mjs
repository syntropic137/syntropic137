#!/usr/bin/env node
// Token usage gate: every --sky-* / --ds-* custom property that Skyline code
// references must resolve under EVERY theme. check-themes.mjs only compares
// the themes with each other, so a token deleted from both passed it; this
// gate compares the themes with their consumers.
//
// A reference resolves when the name is defined by the upstream
// @syntropic137/design-tokens stylesheet, by tokens.css (structural, loaded
// with every theme), by every theme file, or set at runtime by the code
// itself (`--x:` in a style block, `style:--x`, `setProperty('--x')`).
// Dynamic names (`var(--sky-status-${kind})`) must match at least one
// defined token by prefix.
//
// Usage: node check-token-usage.mjs [dir-or-file...]   (default: Skyline sources and themes/src/motion.css)
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const repo = join(here, '../../..')
const themesSrc = join(here, '../themes/src')
const THEMES = ['skyline.css', 'syn137.css']
const DEFAULT_DIRS = ['packages/syn-ui/skyline-svelte-v5/src', 'packages/syn-ui/skyline-core/src', 'apps/syn-ui/src', 'packages/syn-ui/themes/src/motion.css']
const EXTS = ['.svelte', '.css', '.ts']

const stripComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' ')).replace(/<!--[\s\S]*?-->/g, (m) => m.replace(/[^\n]/g, ' '))
const defs = (css) => new Set([...stripComments(css).matchAll(/(--[a-z0-9-]+)\s*:/g)].map((m) => m[1]))

const requireFromThemes = createRequire(join(themesSrc, '..', 'package.json'))
const upstream = defs(readFileSync(requireFromThemes.resolve('@syntropic137/design-tokens/css'), 'utf8'))
const structural = defs(readFileSync(join(themesSrc, 'tokens.css'), 'utf8'))
const perTheme = THEMES.map((f) => [f, defs(readFileSync(join(themesSrc, f), 'utf8'))])

function walk(dir) {
  if (statSync(dir).isFile()) return [dir]
  const out = []
  for (const name of readdirSync(dir)) {
    if (name === 'node_modules' || name === 'generated') continue
    const p = join(dir, name)
    if (statSync(p).isDirectory()) out.push(...walk(p))
    else if (EXTS.some((e) => name.endsWith(e)) && !/\.test\.ts$/.test(name)) out.push(p)
  }
  return out
}

const dirs = (process.argv.slice(2).length ? process.argv.slice(2) : DEFAULT_DIRS).map((d) => join(repo, d))
const files = dirs.flatMap(walk)
const sources = files.map((f) => [f, stripComments(readFileSync(f, 'utf8'))])

// Names the code sets itself.
const local = new Set()
for (const [, src] of sources) {
  for (const m of src.matchAll(/(?<![\w-])(--(?:sky|ds)-[a-z0-9-]+)\s*:(?!:)/g)) local.add(m[1])
  for (const m of src.matchAll(/style:(--(?:sky|ds)-[a-z0-9-]+)/g)) local.add(m[1])
  for (const m of src.matchAll(/setProperty\(\s*['"`](--(?:sky|ds)-[a-z0-9-]+)/g)) local.add(m[1])
}

const always = new Set([...upstream, ...structural, ...local])
const missingIn = (name) => perTheme.filter(([, set]) => !set.has(name)).map(([f]) => f)
const definedAnywhere = [...always, ...perTheme.flatMap(([, s]) => [...s])]

const REF = /var\(\s*(--(?:sky|ds)-[a-z0-9-]*)(\$\{)?|['"`](--(?:sky|ds)-[a-z0-9-]*)(\$\{)?/g
let failed = 0
let refs = 0
for (const [file, src] of sources) {
  const lines = src.split('\n')
  lines.forEach((line, i) => {
    for (const m of line.matchAll(REF)) {
      const name = m[1] ?? m[3]
      const dynamic = Boolean(m[2] ?? m[4])
      refs++
      const where = `${relative(repo, file)}:${i + 1}`
      if (dynamic) {
        if (!definedAnywhere.some((t) => t.startsWith(name) && t.length > name.length)) {
          console.error(`${where}: ${name}\${...} matches no defined token`)
          failed++
        }
        continue
      }
      if (always.has(name)) continue
      const missing = missingIn(name)
      if (missing.length) {
        console.error(`${where}: ${name} is not defined in ${missing.join(', ')}${missing.length === THEMES.length ? ' (nor tokens.css or @syntropic137/design-tokens)' : ''}`)
        failed++
      }
    }
  })
}

if (failed) {
  console.error(`token usage: ${failed} unresolved reference(s)`)
  process.exit(1)
}
console.log(`token usage ok: ${refs} references in ${files.length} files resolve under ${THEMES.join(', ')}`)
