/**
 * The one cube of the brand: every extruded block in Skyline (the S mark,
 * the run city, verdict blocks, object icons, phase blocks, the usage band
 * and the skyline bars) is a box built here.
 *
 * `prism()` is the shared core: a ground parallelogram (an origin corner and
 * two edge vectors) lifted by a height, returned as its eight named corners.
 * Projections only choose the edge vectors:
 * - isometric: both ground edges recede up the screen, left and right of the
 *   front corner (`isoCube`, `isoBox`);
 * - oblique (cabinet): one edge runs flat along the screen, the other
 *   recedes up and to the right (`obliqueBox` in extrude.ts).
 *
 * Coordinates are SVG screen units (y grows downward). Nothing here knows
 * about colour: a cube carries a `tone` name the renderer maps to tokens.
 */
import { type Point, polygonPoints } from './path'

/** Corners of an extruded parallelogram: `g*` on the ground, `t*` lifted by the height. */
export interface PrismCorners {
  /** The origin corner. */
  g0: Point
  /** origin + u */
  gu: Point
  /** origin + v */
  gv: Point
  /** origin + u + v */
  guv: Point
  t0: Point
  tu: Point
  tv: Point
  tuv: Point
}

/** Extrude the ground parallelogram (origin, origin + u, origin + u + v, origin + v) up by `height`. */
export function prism(origin: Point, u: Point, v: Point, height: number): PrismCorners {
  const [x, y] = origin
  const gu: Point = [x + u[0], y + u[1]]
  const gv: Point = [x + v[0], y + v[1]]
  const guv: Point = [gu[0] + v[0], gu[1] + v[1]]
  const up = ([px, py]: Point): Point => [px, py - height]
  return { g0: origin, gu, gv, guv, t0: up(origin), tu: up(gu), tv: up(gv), tuv: up(guv) }
}

/** Diamond half-height over half-width for the 2:1 pixel isometric of the icons, verdict blocks and the city. */
export const ISO_PIXEL = 0.5

/** The S mark's true isometric: half-height 0.5 over half-width 0.866 of the cube edge. */
export const ISO_TRUE = 0.5 / 0.866

/** Corners of an isometric box standing on its front ground corner `front`. */
export function isoCorners(front: Point, width: number, depth: number, height: number, ratio: number = ISO_PIXEL): PrismCorners {
  // u runs to the left ground corner, v to the right one.
  return prism(front, [-width, -width * ratio], [depth, -depth * ratio], height)
}

/** The three visible faces of an isometric cube, as point lists. */
export interface IsoCubePoints {
  /** Diamond, starting at the back corner and going clockwise: back, right, front, left. */
  top: Point[]
  /** Left-facing face (lit, the "front" face of extrudeColors). */
  left: Point[]
  /** Right-facing face (shaded, the "side" face of extrudeColors). */
  right: Point[]
}

/** The three visible faces as SVG `points` attribute strings. */
export interface IsoCubeFaces {
  top: string
  left: string
  right: string
}

export interface IsoCubeInput<T extends string = string> {
  /** Centre of the cube's ground diamond. */
  x: number
  y: number
  /** Half-width of the diamond: how far its left and right corners sit from the centre. */
  size: number
  /** Extrusion above the ground, in screen units. */
  height: number
  /** Colour role the renderer maps to tokens ("blue", "dark", "glass", "failed", ...). */
  tone?: T
  /** Diamond half-height over half-width; ISO_PIXEL (default) or ISO_TRUE. */
  ratio?: number
}

export interface IsoCube<T extends string = string> extends IsoCubeFaces {
  tone: T | undefined
}

/** Face point lists of an isometric cube; `isoCube()` formats them. */
export function isoCubePoints(c: Omit<IsoCubeInput, 'tone'>): IsoCubePoints {
  const ratio = c.ratio ?? ISO_PIXEL
  const k = isoCorners([c.x, c.y + c.size * ratio], c.size, c.size, c.height, ratio)
  return {
    top: [k.tuv, k.tv, k.t0, k.tu],
    left: [k.tu, k.t0, k.g0, k.gu],
    right: [k.t0, k.tv, k.gv, k.g0],
  }
}

/** `isoCube({x, y, size, height, tone})` -> `{top, left, right}` polygon point strings. */
export function isoCube<T extends string = string>(c: IsoCubeInput<T>): IsoCube<T> {
  const p = isoCubePoints(c)
  return { top: polygonPoints(p.top), left: polygonPoints(p.left), right: polygonPoints(p.right), tone: c.tone }
}
