/**
 * Object Icons (CompPatterns sheet): one three-face isometric object per
 * section, in a 64 x 64 box, transcribed from the canvas.
 *
 * Shapes name a face, not a colour. The renderer maps `top`, `front`, `side`
 * to the --sky-face-* tokens (or extrudeColors() of any base) and `ink` to
 * the page ground, so the icons recolour with the theme.
 */
import type { ObjectKind } from '../patterns/types'
import { isoBox } from './extrude'

export type IconFace = 'top' | 'front' | 'side' | 'ink'

export type IconShape =
  | { el: 'polygon'; points: string; face: IconFace; opacity?: number }
  | { el: 'path'; d: string; face: IconFace; opacity?: number }
  /** Ink strokes drawn over a face (the session clock, artifact lines). */
  | { el: 'stroke'; d: string; width: number; opacity?: number }

export interface ObjectIconDef {
  /** Soft accent shadow under the object. */
  glow: { cx: number; cy: number; rx: number; ry: number }
  /** Shapes in paint order; a group opacity applies to every shape in it. */
  groups: { opacity?: number; shapes: IconShape[] }[]
}

const glow = (cy = 59, rx = 18) => ({ cx: 32, cy, rx, ry: 3.5 })

/** One slab of the workflow stack: a 20 x 20 diamond, 5 deep. */
function slab(y: number): IconShape[] {
  const b = isoBox({ x: 32, y: y + 5, width: 20, depth: 20, height: 5 })
  return [
    { el: 'path', d: b.top, face: 'top' },
    { el: 'path', d: b.front, face: 'front' },
    { el: 'path', d: b.side, face: 'side' },
  ]
}

const execution = isoBox({ x: 32, y: 54, width: 20, depth: 20, height: 24 })
const session = isoBox({ x: 32, y: 50, width: 22, depth: 22, height: 10 })

export const OBJECT_ICONS: Record<ObjectKind, ObjectIconDef> = {
  trigger: {
    glow: glow(),
    groups: [
      {
        shapes: [
          { el: 'polygon', points: '38,10 22,36 34,36 30,58 50,28 38,28', face: 'side' },
          { el: 'polygon', points: '34,8 18,34 30,34 26,56 46,26 34,26', face: 'top' },
        ],
      },
    ],
  },
  workflow: {
    glow: glow(),
    groups: [
      { opacity: 0.45, shapes: slab(50) },
      { opacity: 0.72, shapes: slab(39) },
      { shapes: slab(28) },
    ],
  },
  execution: {
    glow: glow(),
    groups: [
      {
        shapes: [
          { el: 'path', d: execution.top, face: 'top' },
          { el: 'path', d: execution.front, face: 'front' },
          { el: 'path', d: execution.side, face: 'side' },
          // The play mark on the front face.
          { el: 'polygon', points: '18,29 18,41 27,39.5', face: 'ink', opacity: 0.8 },
        ],
      },
    ],
  },
  session: {
    glow: glow(),
    groups: [
      {
        shapes: [
          { el: 'path', d: session.top, face: 'top' },
          { el: 'path', d: session.front, face: 'front' },
          { el: 'path', d: session.side, face: 'side' },
          { el: 'stroke', d: 'M34,23L34,28L24,28', width: 2.2, opacity: 0.8 },
          { el: 'stroke', d: 'M32,32L39,35.5', width: 2.2, opacity: 0.8 },
        ],
      },
    ],
  },
  artifact: {
    glow: glow(),
    groups: [
      {
        shapes: [
          { el: 'polygon', points: '26,10 46,20 46,48 26,38', face: 'side' },
          { el: 'polygon', points: '18,16 38,26 38,54 18,44', face: 'top' },
          { el: 'stroke', d: 'M22,25L34,31M22,31L34,37M22,37L30,41', width: 2, opacity: 0.6 },
        ],
      },
    ],
  },
  eval: {
    glow: glow(58, 19),
    groups: [
      {
        shapes: [
          { el: 'polygon', points: '26,9 32,9 32,54 11,54 26,25', face: 'top', opacity: 0.4 },
          { el: 'polygon', points: '32,9 38,9 38,25 53,54 32,54', face: 'side', opacity: 0.55 },
          { el: 'polygon', points: '19.3,38 32,38 32,54 11,54', face: 'front' },
          { el: 'polygon', points: '32,38 44.7,38 53,54 32,54', face: 'side' },
          { el: 'polygon', points: '19.3,38 32,35 44.7,38 32,41', face: 'top' },
          { el: 'polygon', points: '23.5,6 40.5,6 40.5,10 23.5,10', face: 'top' },
        ],
      },
    ],
  },
}

export const OBJECT_KINDS = Object.keys(OBJECT_ICONS) as ObjectKind[]
