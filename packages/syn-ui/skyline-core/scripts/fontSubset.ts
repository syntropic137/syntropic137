/**
 * Embeddable fonts for static SVG assets (repo-banner.ts).
 *
 * GitHub renders README SVGs through <img>, which loads nothing external, so
 * a banner carries its own fonts: each variable woff2 from
 * apps/syn-landing/public/fonts (OFL) is pinned to one static weight with
 * fontTools' instancer, then subset to exactly the glyphs one banner uses
 * and re-encoded as woff2, ready for a data: URI in an @font-face rule.
 * Advance widths come from the same static instance, so layout can measure
 * text without a browser.
 *
 * fontTools runs through uvx (Python only via uv); nothing is installed in
 * the workspace:
 *   uvx --from fonttools --with brotli fonttools varLib.instancer ...
 *   uvx --from fonttools --with brotli pyftsubset ...
 */
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

export interface FontSpec {
  /** CSS family name the SVG uses. */
  family: string
  /** Source woff2 (variable). */
  file: string
  /** Axis pins for the static instance, e.g. { wght: 600 }. */
  axes: Record<string, number>
  /** CSS weight the @font-face declares. */
  weight: number
}

export interface StaticFont {
  spec: FontSpec
  ttf: string
  unitsPerEm: number
  /** Cap height (OS/2 sCapHeight) as a fraction of the em. */
  cap: number
  /** Advance width per character, in font units. */
  advances: Map<string, number>
}

const FONTTOOLS = ['--from', 'fonttools', '--with', 'brotli']

function uvx(args: string[]): string {
  // SOURCE_DATE_EPOCH pins head.modified, so the same input gives byte-identical fonts.
  const env = { ...process.env, SOURCE_DATE_EPOCH: '0' }
  return execFileSync('uvx', [...FONTTOOLS, ...args], { encoding: 'utf8', env, stdio: ['ignore', 'pipe', 'pipe'], maxBuffer: 64 << 20 })
}

let workDir: string | undefined
function work(): string {
  workDir ??= mkdtempSync(join(tmpdir(), 'syn-banner-fonts-'))
  return workDir
}

/** Advance widths by character, read from a ttx dump of cmap and hmtx. */
function readMetrics(ttf: string): { unitsPerEm: number; cap: number; advances: Map<string, number> } {
  const xml = uvx(['fonttools', 'ttx', '-q', '-t', 'head', '-t', 'OS/2', '-t', 'cmap', '-t', 'hmtx', '-o', '-', ttf])
  const unitsPerEm = Number(/<unitsPerEm value="(\d+)"/.exec(xml)?.[1] ?? 1000)
  const cap = Number(/<sCapHeight value="(\d+)"/.exec(xml)?.[1] ?? unitsPerEm * 0.7) / unitsPerEm
  const widths = new Map<string, number>()
  for (const m of xml.matchAll(/<mtx name="([^"]+)" width="(\d+)"/g)) widths.set(m[1] ?? '', Number(m[2]))
  const advances = new Map<string, number>()
  for (const m of xml.matchAll(/<map code="(0x[0-9a-f]+)" name="([^"]+)"/g)) {
    const w = widths.get(m[2] ?? '')
    if (w !== undefined) advances.set(String.fromCodePoint(Number(m[1])), w)
  }
  return { unitsPerEm, cap, advances }
}

/** Pin a variable font to one static instance and read its metrics. */
export function staticFont(spec: FontSpec): StaticFont {
  const ttf = join(work(), `${spec.family.replace(/\W+/g, '-')}-${spec.weight}.ttf`)
  const pins = Object.entries(spec.axes).map(([axis, v]) => `${axis}=${v}`)
  uvx(['fonttools', 'varLib.instancer', '-q', spec.file, ...pins, '-o', ttf])
  return { spec, ttf, ...readMetrics(ttf) }
}

/** Width of `text` at `size` px, with `tracking` em of letter spacing after each glyph. */
export function measure(font: StaticFont, text: string, size: number, tracking = 0): number {
  let units = 0
  for (const ch of text) units += font.advances.get(ch) ?? font.unitsPerEm * 0.6
  return (units / font.unitsPerEm) * size + [...text].length * tracking * size
}

/** The glyphs for `text` only, as a woff2 data: URI. */
export function subsetDataUri(font: StaticFont, text: string): string {
  const glyphs = [...new Set(text)].sort().join('')
  const out = join(work(), `${font.spec.family.replace(/\W+/g, '-')}-${font.spec.weight}-subset.woff2`)
  uvx([
    'pyftsubset',
    font.ttf,
    `--text=${glyphs}`,
    '--flavor=woff2',
    '--layout-features=kern',
    '--no-hinting',
    '--desubroutinize',
    '--name-IDs=1,2',
    `--output-file=${out}`,
  ])
  return `data:font/woff2;base64,${readFileSync(out).toString('base64')}`
}

/** An @font-face rule embedding the subset for `text`. */
export function fontFace(font: StaticFont, text: string): string {
  return `@font-face{font-family:'${font.spec.family}';font-weight:${font.spec.weight};font-style:normal;src:url(${subsetDataUri(font, text)}) format('woff2')}`
}
