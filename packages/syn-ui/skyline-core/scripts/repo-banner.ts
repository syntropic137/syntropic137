/**
 * README banners for the org's repos: the cube S on the left; on the right a
 * pill (license and a short label), the repo's display name in Orbitron, a
 * tagline and its key command, over the landing ground (accent glow wash,
 * 28px dot grid). One SVG per entry in
 * design/brand/banners/repos.json, written to design/brand/banners/<name>.svg.
 *
 *   pnpm --filter @syn137/skyline-core run repo-banner [name ...]
 *
 * GitHub shows README SVGs as <img>, which loads nothing external, so each
 * banner embeds its fonts as subset woff2 data: URIs (fontSubset.ts; needs
 * uv on PATH). The CSS font stacks still list fallbacks for renderers that
 * ignore @font-face (rsvg-convert, some previewers).
 */
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { sMark } from '../src/geometry/index.ts'
import { ACCENT, cube, GROUND, S_FACES, TEXT } from './brand.ts'
import { type FontSpec, fontFace, measure, type StaticFont, staticFont } from './fontSubset.ts'

export interface BannerSpec {
  name: string
  title: string
  label: string
  license?: string
  tagline?: string
  command?: string
  alt?: string
}

const W = 1200
const H = 400
const RADIUS = 24
const TEXT_X = 414
const TEXT_MAX = W - TEXT_X - 88
const MARK_CX = 236

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../../..')
const fontDir = resolve(root, 'apps/syn-landing/public/fonts')
const outDir = resolve(root, 'design/brand/banners')

const FONTS: Record<'brand' | 'sans' | 'mono', FontSpec> = {
  brand: { family: 'Orbitron', file: resolve(fontDir, 'orbitron-latin.woff2'), axes: { wght: 600 }, weight: 600 },
  sans: { family: 'Instrument Sans', file: resolve(fontDir, 'instrument-sans-latin.woff2'), axes: { wght: 400 }, weight: 400 },
  mono: { family: 'JetBrains Mono', file: resolve(fontDir, 'jetbrains-mono-latin.woff2'), axes: { wght: 500 }, weight: 500 },
}
const STACK = {
  brand: "'Orbitron','Eurostile','Instrument Sans',system-ui,sans-serif",
  sans: "'Instrument Sans',ui-sans-serif,system-ui,-apple-system,'Segoe UI',sans-serif",
  mono: "'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace",
}

/** Type scale (px) and letter spacing (em). Tracking matches the landing (--sky-tracking-brand, pill caps). */
const TYPE = {
  title: { max: 92, tracking: 0.04, cap: 0.72 },
  tagline: { size: 25, cap: 0.7 },
  command: { max: 20, cap: 0.73 },
  pill: { size: 13, tracking: 0.12, height: 34 },
}
const GAP = { pillTitle: 30, titleTagline: 36, taglineCommand: 26 }

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
const n = (v: number) => Math.round(v * 10) / 10

type Fonts = Record<keyof typeof FONTS, StaticFont>

// ---------------------------------------------------------------- ground

function defs(): string {
  return `<clipPath id="card"><rect width="${W}" height="${H}" rx="${RADIUS}"/></clipPath>
<radialGradient id="wash" cx="0.72" cy="0" r="0.75" gradientTransform="matrix(1 0 0 1.6 0 0)"><stop offset="0" stop-color="${ACCENT}" stop-opacity="0.26"/><stop offset="1" stop-color="${ACCENT}" stop-opacity="0"/></radialGradient>
<radialGradient id="markglow"><stop offset="0" stop-color="${ACCENT}" stop-opacity="0.34"/><stop offset="1" stop-color="${ACCENT}" stop-opacity="0"/></radialGradient>
<pattern id="dots" width="28" height="28" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="${TEXT.muted}" fill-opacity="0.16"/></pattern>
<linearGradient id="edge" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="${ACCENT}" stop-opacity="0"/><stop offset="0.5" stop-color="${ACCENT}" stop-opacity="0.7"/><stop offset="1" stop-color="${ACCENT}" stop-opacity="0"/></linearGradient>`
}

function ground(): string {
  return `<g clip-path="url(#card)">
<rect width="${W}" height="${H}" fill="${GROUND}"/>
<rect width="${W}" height="${H}" fill="url(#dots)"/>
<rect width="${W}" height="${H}" fill="url(#wash)"/>
<ellipse cx="${MARK_CX}" cy="${H / 2 + 24}" rx="200" ry="180" fill="url(#markglow)"/>
<rect x="${W * 0.2}" y="0" width="${W * 0.6}" height="1" fill="url(#edge)"/>
</g>
<rect x="0.5" y="0.5" width="${W - 1}" height="${H - 1}" rx="${RADIUS - 0.5}" fill="none" stroke="${TEXT.muted}" stroke-opacity="0.16"/>`
}

function mark(): string {
  const m = sMark(34)
  const x = MARK_CX - m.width / 2
  const y = (H - m.height) / 2
  return `<g transform="translate(${n(x)} ${n(y)})">${m.cubes.map((c) => cube(S_FACES[c.tone], c)).join('')}</g>`
}

// ---------------------------------------------------------------- text

/** The scales glyph for the license, drawn so it needs no font. */
function scales(x: number, cy: number): string {
  const s = `fill="none" stroke="${ACCENT}" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"`
  return `<g transform="translate(${n(x)} ${n(cy - 7)})" ${s}><path d="M7 1v12M3.5 13h7M2 3.5h10"/><path d="M3 3.5 1 8.2h4zM11 3.5 9 8.2h4z"/></g>`
}

function pillTexts(spec: BannerSpec): string[] {
  return [spec.license, spec.label].filter((t): t is string => Boolean(t)).map((t) => t.toUpperCase())
}

function pill(spec: BannerSpec, mono: StaticFont, top: number): string {
  const { size, tracking, height } = TYPE.pill
  const cy = top + height / 2
  const base = n(cy + size * 0.36)
  const parts: string[] = []
  let x = TEXT_X + 16
  if (spec.license) {
    parts.push(scales(x, cy))
    x += 14 + 9
  }
  pillTexts(spec).forEach((t, i) => {
    if (i > 0) {
      parts.push(`<rect x="${n(x - size * tracking + 10)}" y="${n(cy - 8)}" width="1" height="16" fill="${ACCENT}" fill-opacity="0.35"/>`)
      x += 21 - size * tracking
    }
    parts.push(`<text x="${n(x)}" y="${base}" font-family="${STACK.mono}" font-size="${size}" font-weight="500" letter-spacing="${tracking}em" fill="${ACCENT}">${esc(t)}</text>`)
    x += measure(mono, t, size, tracking)
  })
  const w = x - TEXT_X + 16 - size * tracking
  const box = `<rect x="${TEXT_X + 0.5}" y="${top + 0.5}" width="${n(w)}" height="${height - 1}" rx="${(height - 1) / 2}" fill="${ACCENT}" fill-opacity="0.09" stroke="${ACCENT}" stroke-opacity="0.32"/>`
  return box + parts.join('')
}

/** The title, any "137" in the accent (the wordmark convention). */
function titleSpans(title: string): string {
  return title
    .split(/(137)/)
    .filter(Boolean)
    .map((p) => (p === '137' ? `<tspan fill="${ACCENT}">137</tspan>` : esc(p)))
    .join('')
}

const fit = (font: StaticFont, text: string, max: number, tracking = 0) => Math.min(max, TEXT_MAX / (measure(font, text, 1, tracking) - tracking))

interface Row {
  height: number
  gapBefore: number
  draw: (top: number) => string
}

function rows(spec: BannerSpec, fonts: Fonts): Row[] {
  const t = TYPE.title
  const titleSize = fit(fonts.brand, spec.title, t.max, t.tracking)
  const out: Row[] = [
    { height: TYPE.pill.height, gapBefore: 0, draw: (top) => pill(spec, fonts.mono, top) },
    {
      height: titleSize * t.cap,
      gapBefore: GAP.pillTitle,
      draw: (top) =>
        `<text x="${TEXT_X - titleSize * 0.04}" y="${n(top + titleSize * t.cap)}" font-family="${STACK.brand}" font-size="${n(titleSize)}" font-weight="600" letter-spacing="${t.tracking}em" fill="${TEXT.fg}">${titleSpans(spec.title)}</text>`,
    },
  ]
  if (spec.tagline) {
    const s = TYPE.tagline.size
    out.push({
      height: s * TYPE.tagline.cap,
      gapBefore: GAP.titleTagline,
      draw: (top) => `<text x="${TEXT_X}" y="${n(top + s * TYPE.tagline.cap)}" font-family="${STACK.sans}" font-size="${s}" fill="${TEXT.muted}">${esc(spec.tagline ?? '')}</text>`,
    })
  }
  if (spec.command) out.push(commandRow(spec.command, fonts.mono))
  return out
}

function commandRow(command: string, mono: StaticFont): Row {
  const line = `$ ${command}`
  const s = fit(mono, line, TYPE.command.max)
  const cap = TYPE.command.cap
  return {
    height: s * cap,
    gapBefore: GAP.taglineCommand,
    draw: (top) =>
      `<text x="${TEXT_X}" y="${n(top + s * cap)}" font-family="${STACK.mono}" font-size="${n(s)}" font-weight="500" fill="${TEXT.fg}" fill-opacity="0.86" xml:space="preserve"><tspan fill="${ACCENT}">$</tspan> ${esc(command)}</text>`,
  }
}

function textBlock(spec: BannerSpec, fonts: Fonts): string {
  const list = rows(spec, fonts)
  const total = list.reduce((sum, r) => sum + r.gapBefore + r.height, 0)
  let top = (H - total) / 2
  return list
    .map((r) => {
      top += r.gapBefore
      const svg = r.draw(top)
      top += r.height
      return svg
    })
    .join('\n')
}

// ---------------------------------------------------------------- banner

function styles(spec: BannerSpec, fonts: Fonts): string {
  const mono = [...pillTexts(spec), spec.command ? `$ ${spec.command}` : ''].join('')
  return [fontFace(fonts.brand, spec.title), spec.tagline ? fontFace(fonts.sans, spec.tagline) : '', fontFace(fonts.mono, mono)].join('\n')
}

export function banner(spec: BannerSpec, fonts: Fonts): string {
  const label = spec.alt ?? `${spec.title}: ${spec.tagline ?? spec.label}`
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">
<title>${esc(label)}</title>
<style>
${styles(spec, fonts)}
</style>
<defs>
${defs()}
</defs>
${ground()}
${mark()}
${textBlock(spec, fonts)}
</svg>
`
}

function main(): void {
  const config = JSON.parse(readFileSync(resolve(outDir, 'repos.json'), 'utf8')) as { repos: BannerSpec[] }
  const only = new Set(process.argv.slice(2))
  const fonts: Fonts = { brand: staticFont(FONTS.brand), sans: staticFont(FONTS.sans), mono: staticFont(FONTS.mono) }
  for (const spec of config.repos.filter((r) => only.size === 0 || only.has(r.name))) {
    const path = resolve(outDir, `${spec.name}.svg`)
    const svg = banner(spec, fonts)
    writeFileSync(path, svg)
    console.log(`wrote ${path} (${(Buffer.byteLength(svg) / 1024).toFixed(1)} KB)`)
  }
}

main()
