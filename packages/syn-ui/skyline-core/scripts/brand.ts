/**
 * Fixed brand colours and the isometric cube drawer shared by the static
 * brand-asset scripts (og-image.ts, repo-banner.ts).
 *
 * Colour literals are allowed here only because the outputs are static
 * assets that can't read CSS variables. They mirror design/brand/s-mark.svg
 * (S faces) and the syn137 theme (ground #0A0C14, accent #4D80FF, status
 * red and amber, text colours).
 */
import type { HeroCityTone, SMarkTone } from '../src/geometry/index.ts'

export const GROUND = '#0A0C14'
export const ACCENT = '#4D80FF'
/** --ds-color-fg, --ds-color-text-muted, --ds-color-text-subtle (syn137 theme). */
export const TEXT = { fg: '#E8EEFB', muted: '#9AA8C7', subtle: '#6F7FA3' } as const

export interface Faces {
  left: string
  right: string
  top: string
  stroke?: string
}

/** Face fills as in s-mark.svg: left is the base, right shaded, top lit. */
export const S_FACES: Record<SMarkTone, Faces> = {
  blue: { left: ACCENT, right: '#22396F', top: '#A9C1FF' },
  dark: { left: '#1C2236', right: '#10141F', top: '#2B3350', stroke: 'rgba(120,140,190,0.10)' },
  glass: { left: 'rgba(232,238,251,0.32)', right: 'rgba(232,238,251,0.18)', top: 'rgba(255,255,255,0.55)', stroke: 'rgba(255,255,255,0.55)' },
}

export const CITY_FACES: Record<HeroCityTone, Faces> = {
  run: S_FACES.blue,
  live: S_FACES.blue,
  failed: { left: '#FF6F61', right: '#803831', top: '#FFACA3' },
  errored: { left: '#E5B450', right: '#735A28', top: '#F0D399' },
}

/** One isometric cube as three polygons. */
export function cube(f: Faces, p: { left: string; right: string; top: string }, attrs = ''): string {
  const st = f.stroke ? ` stroke="${f.stroke}" stroke-width="1"` : ''
  return `<g${attrs}><polygon points="${p.left}" fill="${f.left}"${st}/><polygon points="${p.right}" fill="${f.right}"${st}/><polygon points="${p.top}" fill="${f.top}"${st}/></g>`
}
