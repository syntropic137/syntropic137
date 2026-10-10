/**
 * 3D extrusion: the three visible faces of a box, in two projections, plus
 * the colour recipe for each face.
 *
 * Colour: the front face is the base colour, the top face is mixed 58%
 * toward the foreground, the side face 50% toward the ground. Returned as
 * color-mix() strings over CSS custom properties, so the result recolours
 * with any theme and never contains a colour literal.
 */
import { type Point, polygonPath } from './path'

export type Face = 'front' | 'top' | 'side'

export interface FaceColors {
  front: string
  top: string
  side: string
}

export interface ExtrudeColorOptions {
  /** Light the top toward this colour (default the theme foreground). */
  light?: string
  /** Shade the side toward this colour (default the theme ground). */
  shade?: string
  /** Share of the base colour in the top face, percent (default 58). */
  topMix?: number
  /** Share of the base colour in the side face, percent (default 50). */
  sideMix?: number
}

/**
 * Face colours for a base colour expression, e.g. `var(--ds-color-accent)`
 * or `var(--sky-color-data-2)`.
 */
export function extrudeColors(base = 'var(--ds-color-accent)', options: ExtrudeColorOptions = {}): FaceColors {
  const light = options.light ?? 'var(--ds-color-fg)'
  const shade = options.shade ?? 'var(--ds-color-bg)'
  const topMix = options.topMix ?? 58
  const sideMix = options.sideMix ?? 50
  return {
    front: base,
    top: `color-mix(in oklab, ${base} ${topMix}%, ${light})`,
    side: `color-mix(in oklab, ${base} ${sideMix}%, ${shade})`,
  }
}

export interface FacePaths {
  front: string
  top: string
  side: string
}

export interface ObliqueBox {
  /** Left edge of the front face. */
  x: number
  /** Ground line (bottom of the front face). SVG y grows downward. */
  y: number
  width: number
  /** Extrusion height above the ground line; 0 draws only the floor tile. */
  height: number
  /** Depth offset of the back edge: right by dx, up by dy. */
  dx: number
  dy: number
}

/**
 * Oblique (cabinet) box: a front rectangle with the top and right side
 * receding by (dx, -dy). This is the Skyline chart and Usage Meter band.
 */
export function obliqueBox(b: ObliqueBox): FacePaths {
  const { x, y, width: w, height: h, dx, dy } = b
  const front: Point[] = [[x, y], [x + w, y], [x + w, y - h], [x, y - h]]
  const side: Point[] = [[x + w, y], [x + w + dx, y - dy], [x + w + dx, y - dy - h], [x + w, y - h]]
  const top: Point[] = [[x, y - h], [x + w, y - h], [x + w + dx, y - h - dy], [x + dx, y - h - dy]]
  return {
    front: h > 0 ? polygonPath(front) : '',
    side: h > 0 ? polygonPath(side) : '',
    top: polygonPath(top),
  }
}

/** The floor tile under an empty oblique cell (the top face at height 0). */
export function obliqueFloor(b: Omit<ObliqueBox, 'height'>): string {
  return obliqueBox({ ...b, height: 0 }).top
}

export interface IsoBox {
  /** Screen position of the nearest ground corner (bottom of the front edge). */
  x: number
  y: number
  /** Extent along the left axis (screen: up-left, slope 1/2). */
  width: number
  /** Extent along the right axis (screen: up-right, slope 1/2). */
  depth: number
  height: number
}

/**
 * Isometric (2:1) box, as in the object icons: a diamond top, the
 * left-facing front face and the right-facing side face.
 *
 * The Execution icon is isoBox({ x: 32, y: 54, width: 20, depth: 20, height: 24 }).
 */
export function isoBox(b: IsoBox): FacePaths {
  const { x, y, width: w, depth: d, height: h } = b
  const F: Point = [x, y]
  const L: Point = [x - w, y - w / 2]
  const R: Point = [x + d, y - d / 2]
  const up = ([px, py]: Point): Point => [px, py - h]
  const B: Point = [L[0] + R[0] - F[0], L[1] + R[1] - F[1]]
  return {
    top: polygonPath([up(F), up(R), up(B), up(L)]),
    front: polygonPath([up(L), up(F), F, L]),
    side: polygonPath([up(F), up(R), R, F]),
  }
}
