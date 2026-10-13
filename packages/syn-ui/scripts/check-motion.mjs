#!/usr/bin/env node
// Motion gate for the themes package (landing plan, rule 7).
//
// In every given CSS file:
//   - each @keyframes block and each animation / animation-name declaration
//     must sit inside @media (prefers-reduced-motion: no-preference), so the
//     default (reduced motion, or no match) is the static end state;
//   - nothing may loop forever: no `infinite` (the landing energy test
//     measures idle CPU after 35s).
//
// Usage: node check-motion.mjs [file.css ...]   (default: themes/src/*.css)
import { readdirSync, readFileSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const src = join(dirname(fileURLToPath(import.meta.url)), '../themes/src')
const args = process.argv.slice(2)
const files = args.length ? args : readdirSync(src).filter((f) => f.endsWith('.css')).map((f) => join(src, f))

const GUARD = /@media[^{]*prefers-reduced-motion\s*:\s*no-preference/
const lineOf = (text, idx) => text.slice(0, idx).split('\n').length

let problems = 0
let checked = 0
const report = (file, text, idx, msg) => {
  console.error(`${relative(process.cwd(), file)}:${lineOf(text, idx)}: ${msg}`)
  problems++
}

for (const file of files) {
  const text = readFileSync(file, 'utf8')
  // Blank out comments and strings, keeping offsets, so neither can fake a brace or a match.
  const css = text
    .replace(/\/\*[\s\S]*?\*\//g, (c) => c.replace(/[^\n]/g, ' '))
    .replace(/"[^"\n]*"|'[^'\n]*'/g, (s) => s.replace(/[^\n]/g, ' '))

  const stack = [] // preludes of the open blocks, outermost first
  let start = 0 // where the current prelude or declaration begins
  const guarded = () => stack.some((p) => GUARD.test(p))
  const checkDecl = (end) => {
    const decl = css.slice(start, end)
    const m = decl.match(/^\s*(animation(?:-name)?)\s*:/)
    if (!m) return
    checked++
    if (!guarded()) report(file, text, start + decl.indexOf(m[1]), `${m[1]} outside @media (prefers-reduced-motion: no-preference)`)
  }

  for (let i = 0; i < css.length; i++) {
    const ch = css[i]
    if (ch === '{') {
      const prelude = css.slice(start, i).trim()
      if (/^@keyframes\b/.test(prelude)) {
        checked++
        if (!guarded()) report(file, text, start + css.slice(start, i).indexOf('@keyframes'), `${prelude} outside @media (prefers-reduced-motion: no-preference)`)
      }
      stack.push(prelude)
      start = i + 1
    } else if (ch === ';') {
      checkDecl(i)
      start = i + 1
    } else if (ch === '}') {
      checkDecl(i)
      stack.pop()
      start = i + 1
    }
  }

  for (const m of css.matchAll(/\binfinite\b/g)) report(file, text, m.index, 'infinite animation (run a few cycles and stop)')
}

if (problems) {
  console.error(`\nmotion: ${problems} problem(s). Keyframes and animations go inside @media (prefers-reduced-motion: no-preference) and end.`)
  process.exit(1)
}
console.log(`motion ok: ${checked} keyframes and animation declarations guarded in ${files.length} file(s)`)
