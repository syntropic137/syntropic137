/**
 * Social image (Open Graph / Twitter card): the S over the run city, from
 * the same geometry the page uses (isoCity() with the hero's sample days,
 * sMark()). Writes design/brand/og-image.svg (1200 x 630) and renders
 * design/brand/og-image.png with rsvg-convert.
 *
 *   pnpm --filter @syn137/skyline-core run og-image
 *
 * Colour literals are allowed here only because the output is a static
 * asset that can't read CSS variables. They mirror design/brand/s-mark.svg
 * (accent faces) and the theme (ground --ds-color-bg #0A0C14, status red
 * and amber).
 */
import { execFileSync } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { type CityTone, isoCity, SAMPLE_SESSIONS, sampleCityDays, sMark, type SMarkTone } from '../src/geometry/index.ts'

const W = 1200
const H = 630
const GROUND = '#0A0C14'
const ACCENT = '#4D80FF'

interface Faces {
  left: string
  right: string
  top: string
  stroke?: string
}

/** Face fills as in s-mark.svg: left is the base, right shaded, top lit. */
const S_FACES: Record<SMarkTone, Faces> = {
  blue: { left: ACCENT, right: '#22396F', top: '#A9C1FF' },
  dark: { left: '#1C2236', right: '#10141F', top: '#2B3350', stroke: 'rgba(120,140,190,0.10)' },
  glass: { left: 'rgba(232,238,251,0.32)', right: 'rgba(232,238,251,0.18)', top: 'rgba(255,255,255,0.55)', stroke: 'rgba(255,255,255,0.55)' },
}

const CITY_FACES: Record<CityTone, Faces> = {
  run: S_FACES.blue,
  live: S_FACES.blue,
  failed: { left: '#FF6F61', right: '#803831', top: '#FFACA3' },
  errored: { left: '#E5B450', right: '#735A28', top: '#F0D399' },
}

function cube(f: Faces, p: { left: string; right: string; top: string }, attrs = ''): string {
  const st = f.stroke ? ` stroke="${f.stroke}" stroke-width="1"` : ''
  return `<g${attrs}><polygon points="${p.left}" fill="${f.left}"${st}/><polygon points="${p.right}" fill="${f.right}"${st}/><polygon points="${p.top}" fill="${f.top}"${st}/></g>`
}

// The hero city (desktop board), seen from a little further back.
const city = isoCity(sampleCityDays(26, 11, '2026-10-08'), {
  cols: 26,
  rows: 11,
  cell: 36,
  live: [150, 171, 199, 222],
  failed: [88, 260],
  errored: [141],
  maxSessions: SAMPLE_SESSIONS,
})
const cityScale = 1.4
const cityX = (W - city.width * cityScale) / 2
const cityY = H - city.height * cityScale + 120
const cityBlocks = city.blocks.map((b) => cube(CITY_FACES[b.tone], b, ` opacity="${b.opacity}"`)).join('')

// The S, standing in the middle of the city.
const mark = sMark(40)
const markScale = 1.6
const markX = (W - mark.width * markScale) / 2
const markY = (H - mark.height * markScale) / 2 - 6
const markCubes = mark.cubes.map((c) => cube(S_FACES[c.tone], c)).join('')

const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Syntropic137: the S mark over a city of agent runs">
<defs>
<radialGradient id="glow" cx="50%" cy="62%" r="60%"><stop offset="0" stop-color="${ACCENT}" stop-opacity="0.30"/><stop offset="1" stop-color="${ACCENT}" stop-opacity="0"/></radialGradient>
<radialGradient id="halo" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="${GROUND}" stop-opacity="1"/><stop offset="0.6" stop-color="${GROUND}" stop-opacity="0.85"/><stop offset="1" stop-color="${GROUND}" stop-opacity="0"/></radialGradient>
<linearGradient id="fade" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${GROUND}" stop-opacity="1"/><stop offset="0.3" stop-color="${GROUND}" stop-opacity="0"/><stop offset="0.85" stop-color="${GROUND}" stop-opacity="0"/><stop offset="1" stop-color="${GROUND}" stop-opacity="0.85"/></linearGradient>
<radialGradient id="markglow" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="${ACCENT}" stop-opacity="0.35"/><stop offset="1" stop-color="${ACCENT}" stop-opacity="0"/></radialGradient>
</defs>
<rect width="${W}" height="${H}" fill="${GROUND}"/>
<rect width="${W}" height="${H}" fill="url(#glow)"/>
<g transform="translate(${cityX.toFixed(1)} ${cityY.toFixed(1)}) scale(${cityScale})" opacity="0.62">
<polygon points="${city.floor}" fill="none" stroke="#1A2032" stroke-width="1"/>
${cityBlocks}
</g>
<rect width="${W}" height="${H}" fill="url(#fade)"/>
<ellipse cx="${W / 2}" cy="${H / 2}" rx="270" ry="330" fill="url(#halo)"/>
<ellipse cx="${W / 2}" cy="${H / 2 + 20}" rx="190" ry="230" fill="url(#markglow)"/>
<g transform="translate(${markX.toFixed(1)} ${markY.toFixed(1)}) scale(${markScale})">${markCubes}</g>
</svg>
`

const brand = resolve(dirname(fileURLToPath(import.meta.url)), '../../../../design/brand')
const svgPath = resolve(brand, 'og-image.svg')
const pngPath = resolve(brand, 'og-image.png')
writeFileSync(svgPath, svg)
execFileSync('rsvg-convert', ['-w', String(W), '-h', String(H), svgPath, '-o', pngPath])
console.log(`wrote ${svgPath}\nwrote ${pngPath}`)
