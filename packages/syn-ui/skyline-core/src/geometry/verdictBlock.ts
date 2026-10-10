/**
 * Verdict Block (Evals board, CompPatterns sheet): one run's verdict as an
 * isometric block. Height carries the verdict before colour does: tall pass,
 * short fail or scorer error, flat unscored.
 */
import { type FacePaths, isoBox } from './extrude'

export type Verdict = 'pass' | 'fail' | 'error' | 'unscored'

/** Block heights in the 56 x 48 box. */
export const VERDICT_HEIGHT: Record<Verdict, number> = { pass: 24, fail: 9, error: 9, unscored: 3 }

/** Sparkline bar heights in px (Evals list). */
export const VERDICT_BAR: Record<Verdict, number> = { pass: 16, fail: 8, error: 8, unscored: 3 }

export const VERDICT_BOX = { width: 56, height: 48, x: 28, y: 42, size: 16, glow: { cx: 28, cy: 43, rx: 15, ry: 3.2 } } as const

/** Faces of a verdict block, in the 56 x 48 viewBox. */
export function verdictBlock(verdict: Verdict): FacePaths {
  const b = VERDICT_BOX
  return isoBox({ x: b.x, y: b.y, width: b.size, depth: b.size, height: VERDICT_HEIGHT[verdict] })
}
