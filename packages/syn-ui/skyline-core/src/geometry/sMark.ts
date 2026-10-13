/**
 * The S mark, in cubes (design/brand/s-mark.svg; ported from s_mark() in
 * design/reference/gen_landing3.py).
 *
 * Eleven true-isometric cubes stand in one vertical plane that runs down and
 * to the right. Rows of S_GRID go top to bottom, columns left to right:
 * B blue (the accent), D dark, G glass, `.` empty. Cubes are returned in
 * draw order (back to front: by column, then bottom to top), which is also
 * the order the landing animation drops them in.
 *
 * sMark(40) reproduces design/brand/s-mark.svg (viewBox 0 0 147 308).
 */
import { ISO_TRUE, type IsoCube, isoCube } from './isoCube'

export type SMarkTone = 'blue' | 'dark' | 'glass'

export const S_GRID = ['BBG', 'B..', 'DDD', '..D', 'DDD'] as const

const TONE: Record<string, SMarkTone> = { B: 'blue', D: 'dark', G: 'glass' }

/** Horizontal half-width of a cube over its edge (cos 30, as the brand file was drawn). */
const HALF_WIDTH = 0.866

export interface SMarkCube extends IsoCube<SMarkTone> {
  tone: SMarkTone
  /** Position in draw order, 0 first. */
  order: number
  /** Column along the plane, 0 at the left. */
  column: number
  /** Height level, 0 at the bottom. */
  level: number
}

export interface SMarkLayout {
  cubes: SMarkCube[]
  width: number
  height: number
  viewBox: string
}

export interface SMarkOptions {
  /** Margin around the mark, in viewBox units (default 4, as in the brand file). */
  pad?: number
}

/** The S as cubes of edge `cubeSize`, in draw order. */
export function sMark(cubeSize = 40, options: SMarkOptions = {}): SMarkLayout {
  const pad = options.pad ?? 4
  const hw = cubeSize * HALF_WIDTH
  const hh = cubeSize * 0.5
  const rows = S_GRID.length
  const cells: { column: number; level: number; tone: SMarkTone }[] = []
  S_GRID.forEach((line, r) => {
    ;[...line].forEach((ch, column) => {
      const tone = TONE[ch]
      if (tone) cells.push({ column, level: rows - 1 - r, tone })
    })
  })
  cells.sort((a, b) => a.column - b.column || a.level - b.level)
  // Back ground corner of the cube at column 0, level 0.
  const ox = hw + pad
  const oy = rows * cubeSize + hh + pad
  const cubes = cells.map((c, order): SMarkCube => {
    const x = ox + c.column * hw
    const back = oy + c.column * hh - c.level * cubeSize
    const faces = isoCube({ x, y: back + hh, size: hw, height: cubeSize, ratio: ISO_TRUE, tone: c.tone })
    return { ...faces, tone: c.tone, order, column: c.column, level: c.level }
  })
  const width = Math.round(4 * hw + 2 * pad)
  const height = Math.round(rows * cubeSize + 5 * hh + 2 * pad)
  return { cubes, width, height, viewBox: `0 0 ${width} ${height}` }
}

/** Face fills per tone, as token expressions (design/brand/s-mark.themable.svg): left lit, right shaded, top lightest. */
export interface SMarkFaces {
  left: string
  right: string
  top: string
  /** Hairline round each face; none on the blue cubes. */
  stroke: string | null
}

export const S_MARK_FACES: Record<SMarkTone, SMarkFaces> = {
  blue: {
    left: 'var(--ds-color-accent)',
    right: 'color-mix(in oklab, var(--ds-color-accent) 45%, var(--sky-color-ground-deep))',
    top: 'color-mix(in oklab, var(--ds-color-accent) 62%, var(--sky-color-display-hi))',
    stroke: null,
  },
  dark: {
    left: 'var(--sky-color-cube-dark-left)',
    right: 'var(--sky-color-cube-dark-right)',
    top: 'var(--sky-color-cube-dark-top)',
    stroke: 'var(--sky-color-cube-edge)',
  },
  glass: {
    left: 'var(--sky-cube-glass-left)',
    right: 'var(--sky-cube-glass-right)',
    top: 'var(--sky-color-cube-glass-edge)',
    stroke: 'var(--sky-color-cube-glass-edge)',
  },
}

/** Entrance stagger of the landing S (seconds): the first cube waits 0.25s, each next one 0.09s more. */
export function sMarkDelay(order: number): number {
  return Math.round((0.25 + order * 0.09) * 100) / 100
}
