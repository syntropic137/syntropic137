/**
 * 3D extrusion: the three visible faces of a box, in two projections, plus
 * the colour recipe for each face. Both projections are the shared cube of
 * isoCube.ts (`prism()`); only the edge vectors differ.
 *
 * Colour: the front face is the base colour, the top face is mixed 58%
 * toward the foreground, the side face 50% toward the ground. Returned as
 * color-mix() strings over CSS custom properties, so the result recolours
 * with any theme and never contains a colour literal.
 */
import { isoCorners, prism } from './isoCube'
import { polygonPath } from './path'

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
  const k = prism([x, y], [w, 0], [dx, -dy], h)
  return {
    front: h > 0 ? polygonPath([k.g0, k.gu, k.tu, k.t0]) : '',
    side: h > 0 ? polygonPath([k.gu, k.guv, k.tuv, k.tu]) : '',
    top: polygonPath([k.t0, k.tu, k.tuv, k.tv]),
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
  // The same corners as isoCube(); the top path starts at the front corner.
  const k = isoCorners([b.x, b.y], b.width, b.depth, b.height)
  return {
    top: polygonPath([k.t0, k.tv, k.tuv, k.tu]),
    front: polygonPath([k.tu, k.t0, k.g0, k.gu]),
    side: polygonPath([k.t0, k.tv, k.gv, k.g0]),
  }
}
