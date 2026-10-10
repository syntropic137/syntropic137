/**
 * Social image (Open Graph / Twitter card): the S over the run city, from
 * the same geometry the page uses (isoCity() with the hero's sample days,
 * sMark()). Writes design/brand/og-image.svg (1200 x 630) and renders
 * design/brand/og-image.png with rsvg-convert.
 *
 *   pnpm --filter @syn137/skyline-core run og-image
 *
 * Brand colours and the cube drawer live in brand.ts (shared with
 * repo-banner.ts).
 */
import { execFileSync } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { isoCity, SAMPLE_SESSIONS, sampleCityDays, sMark } from '../src/geometry/index.ts'
import { ACCENT, CITY_FACES, cube, GROUND, S_FACES } from './brand.ts'

const W = 1200
const H = 630

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
