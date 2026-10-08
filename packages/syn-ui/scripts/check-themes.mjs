#!/usr/bin/env node
// Theme parity gate: every theme file must define exactly the same set of
// custom properties, so switching data-theme never leaves a token unset.
// Also checks that tokens.css (structural) holds no colour literals.
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

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

const tokens = readFileSync(join(src, 'tokens.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
const literal = tokens.match(/#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(/)
if (literal) { console.error(`tokens.css: colour literal ${literal[0]} (colours belong in a theme file)`); failed = true }

if (failed) process.exit(1)
console.log(`themes ok: ${first[1].size} tokens in each of ${themes.join(', ')}`)
