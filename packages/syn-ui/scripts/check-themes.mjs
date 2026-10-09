#!/usr/bin/env node
// Theme parity gate: every theme file must define exactly the same set of
// custom properties, so switching data-theme never leaves a token unset.
// Also checks that tokens.css and motion.css (structural) hold no colour literals.
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const src = join(dirname(fileURLToPath(import.meta.url)), '../themes/src')
const themes = ['skyline.css', 'syn137.css']
const defined = (css) =>
  new Set([...css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/(--[a-z0-9-]+)\s*:/g)].map((m) => m[1]))

let failed = false
const sets = themes.map((f) => [f, defined(readFileSync(join(src, f), 'utf8'))])
const [first, ...rest] = sets
for (const [name, set] of rest) {
  for (const t of first[1]) if (!set.has(t)) { console.error(`${name}: missing ${t} (defined in ${first[0]})`); failed = true }
  for (const t of set) if (!first[1].has(t)) { console.error(`${first[0]}: missing ${t} (defined in ${name})`); failed = true }
}

const strip = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '')
const tokens = strip(readFileSync(join(src, 'tokens.css'), 'utf8'))
// Structural files (tokens.css, motion.css) hold no colour literals.
for (const [name, css] of [['tokens.css', tokens], ['motion.css', strip(readFileSync(join(src, 'motion.css'), 'utf8'))]]) {
  const literal = css.match(/#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(/)
  if (literal) { console.error(`${name}: colour literal ${literal[0]} (colours belong in a theme file)`); failed = true }
}

// Upstream parity: every --ds-* name Skyline defines is an upstream
// @syntropic137/design-tokens name, or one of the extensions documented in
// tokens.css. Resolved from the themes package, which pins the dependency.
const DS_EXTENSIONS = new Set([
  'ds-border-width', 'ds-radius-xs',
  'ds-font-weight-regular', 'ds-font-weight-medium', 'ds-font-weight-semibold', 'ds-font-weight-bold',
  'ds-line-height-tight', 'ds-line-height-snug', 'ds-line-height-normal', 'ds-line-height-code',
  'ds-space-0', 'ds-space-px', 'ds-space-0-5', 'ds-space-1-5', 'ds-space-2-5', 'ds-space-3-5',
  'ds-space-5', 'ds-space-7', 'ds-space-9', 'ds-space-10', 'ds-space-12', 'ds-space-14', 'ds-space-16',
])
const requireFromThemes = createRequire(join(src, '..', 'package.json'))
const { isTokenName } = await import(pathToFileURL(requireFromThemes.resolve('@syntropic137/design-tokens/names')).href)
const ours = new Set([tokens, ...sets.map(([f]) => readFileSync(join(src, f), 'utf8'))].flatMap((css) => [...defined(css)]))
for (const t of ours) {
  if (!t.startsWith('--ds-')) continue
  const name = t.slice(2)
  if (isTokenName(name) && DS_EXTENSIONS.has(name)) { console.error(`check-themes.mjs: ${t} is now upstream; drop it from DS_EXTENSIONS and review its value`); failed = true }
  if (!isTokenName(name) && !DS_EXTENSIONS.has(name)) { console.error(`${t}: not an @syntropic137/design-tokens name; use --sky-* or document it in tokens.css and DS_EXTENSIONS`); failed = true }
}

if (failed) process.exit(1)
console.log(`themes ok: ${first[1].size} tokens in each of ${themes.join(', ')}`)
