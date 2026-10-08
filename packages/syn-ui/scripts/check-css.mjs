#!/usr/bin/env node
// Skyline CSS gate (stopgap for the upstream verify-design-system gate).
//
// In the given directories, CSS in .css files and in .svelte <style> blocks
// and style="" attributes must not contain:
//   - colour literals (#hex, rgb(), hsl(), oklch(), named colours)
//   - var() fallbacks, e.g. var(--ds-color-fg, #fff)
// SVG fill/stroke attributes in .svelte markup must not use hex colours either.
// Colours come only from var(--ds-*) / var(--sky-*) tokens, set by a theme.
//
// Usage: node check-css.mjs <dir> [<dir> ...]
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const NAMED = 'white|black|red|green|blue|yellow|orange|purple|pink|gray|grey|silver|navy|teal|maroon|olive|lime|aqua|fuchsia'
const rules = [
  [/#[0-9a-fA-F]{3,8}\b/, 'colour literal'],
  [/\b(rgba?|hsla?|oklch|oklab|lab|lch|hwb)\(/, 'colour function literal'],
  [new RegExp(`(?<![\\w-])(${NAMED})(?![\\w-])`), 'named colour'],
  [/var\(\s*--[\w-]+\s*,/, 'var() fallback'],
]

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    if (name === 'node_modules' || name === 'dist' || name.startsWith('.')) continue
    const p = join(dir, name)
    if (statSync(p).isDirectory()) yield* walk(p)
    else if (/\.(css|svelte)$/.test(name)) yield p
  }
}

function cssChunks(file, text) {
  if (file.endsWith('.css')) return [{ css: text, offset: 0 }]
  const chunks = []
  for (const m of text.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)) chunks.push({ css: m[1], offset: m.index + m[0].indexOf(m[1]) })
  for (const m of text.matchAll(/\sstyle="([^"]*)"/g)) chunks.push({ css: m[1], offset: m.index })
  for (const m of text.matchAll(/\s(?:fill|stroke|stop-color|color)="(#[^"]*)"/g)) chunks.push({ css: m[1], offset: m.index })
  return chunks
}

const lineOf = (text, idx) => text.slice(0, idx).split('\n').length
let problems = 0
const dirs = process.argv.slice(2)
if (dirs.length === 0) { console.error('usage: check-css.mjs <dir>...'); process.exit(2) }
for (const dir of dirs) {
  for (const file of walk(dir)) {
    const text = readFileSync(file, 'utf8')
    for (const { css, offset } of cssChunks(file, text)) {
      // Blank out comments but keep offsets stable.
      const clean = css.replace(/\/\*[\s\S]*?\*\//g, (c) => c.replace(/[^\n]/g, ' '))
      for (const [re, what] of rules) {
        const g = new RegExp(re.source, 'g')
        for (const m of clean.matchAll(g)) {
          console.error(`${relative(process.cwd(), file)}:${lineOf(text, offset + m.index)}: ${what}: ${m[0]}`)
          problems++
        }
      }
    }
  }
}
if (problems) { console.error(`\n${problems} CSS problem(s). Use var(--ds-*) / var(--sky-*) tokens; colours live in @syn137/skyline-themes.`); process.exit(1) }
console.log(`css ok: ${dirs.join(', ')}`)
