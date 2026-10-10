/**
 * Phase Blocks (Execution board, "Phase timeline"): phases back to back as
 * extruded blocks. Length is time, height is tokens.
 *
 * Widths share the drawable width in proportion to duration, rounded to one
 * decimal before they are laid end to end, which reproduces the board's
 * coordinates. A phase with no recorded duration (pending, skipped) still
 * gets `minWidth` so it can be seen; heights are linear in tokens with a
 * floor of `minHeight`. Blocks are the brand cube's oblique projection
 * (obliqueBox() on isoCube.ts's prism()), as drawn on the board.
 */
import { type FacePaths, obliqueBox } from './extrude'
import { round2 } from './path'

/** How a block is coloured. Screens never pick colours: map a phase status with `phaseTone()`. */
export type PhaseTone = 'done' | 'running' | 'failed' | 'cancelled' | 'pending'

export interface PhaseBlockInput {
  name: string
  durationMs: number | null | undefined
  tokens: number | null | undefined
  tone?: PhaseTone
  /** Shown under the name when it fits: "118.9s · 143.9K tokens · $0.0798". */
  meta?: string
  /** Shorter fallback when `meta` does not fit: "24.3s". */
  metaShort?: string
}

export interface PhaseBlocksDims {
  width: number
  height: number
  left: number
  right: number
  gap: number
  /** Extrusion depth. */
  dx: number
  dy: number
  /** Ground line (bottom of the front faces). */
  ground: number
  maxHeight: number
  minHeight: number
  minWidth: number
  /** Approximate advance per character, for fitting labels without a DOM. */
  nameCharWidth: number
  metaCharWidth: number
}

export const PHASE_BLOCKS: PhaseBlocksDims = {
  width: 880,
  height: 164,
  left: 20,
  right: 18,
  gap: 8,
  dx: 22,
  dy: 14,
  ground: 112,
  maxHeight: 70,
  minHeight: 8,
  minWidth: 28,
  nameCharWidth: 7.4,
  metaCharWidth: 6.7,
}

export interface PhaseBlock {
  index: number
  name: string
  tone: PhaseTone
  x: number
  width: number
  height: number
  paths: FacePaths
  /** "01", drawn inside the front face when it fits; null otherwise. */
  number: { x: number; y: number; text: string } | null
  label: { x: number; y: number; text: string }
  meta: { x: number; y: number; text: string } | null
}

export interface PhaseBlocksLayout {
  viewBox: string
  blocks: PhaseBlock[]
  totalMs: number
  maxTokens: number
}

const round1 = (v: number) => Math.round(v * 10) / 10

/** First candidate that fits `width` at `charWidth` per character; otherwise the last one, cut with an ellipsis. */
export function fitLabel(candidates: readonly (string | undefined | null)[], width: number, charWidth: number): string {
  const list = candidates.filter((c): c is string => !!c)
  for (const c of list) if (c.length * charWidth <= width) return c
  const last = list[list.length - 1] ?? ''
  const max = Math.floor(width / charWidth)
  if (max <= 1) return ''
  return last.length <= max ? last : `${last.slice(0, max - 1)}…`
}

/** Phase status -> block tone. */
export function phaseTone(status: string | null | undefined): PhaseTone {
  return PHASE_TONE.get((status ?? '').toLowerCase()) ?? 'pending'
}

const PHASE_TONE = new Map<string, PhaseTone>([
  ['completed', 'done'],
  ['succeeded', 'done'],
  ['success', 'done'],
  ['running', 'running'],
  ['in_progress', 'running'],
  ['started', 'running'],
  ['failed', 'failed'],
  ['error', 'failed'],
  ['cancelled', 'cancelled'],
  ['canceled', 'cancelled'],
  ['interrupted', 'cancelled'],
])

/** Duration shares with a floor: tiny shares become `min`, the rest split what remains. */
export function shareWidths(values: readonly number[], available: number, min: number): number[] {
  const n = values.length
  if (n === 0) return []
  if (min * n >= available) return values.map(() => round1(available / n))
  const fixed = new Set<number>()
  for (;;) {
    const share = freeShare(values, fixed, available, min)
    if (!fixUnderMin(values, fixed, share, min)) return values.map((v, i) => (fixed.has(i) ? min : round1(share(v))))
  }
}

/** Width a not-yet-fixed value gets: its share of the room the fixed ones leave. */
function freeShare(values: readonly number[], fixed: ReadonlySet<number>, available: number, min: number): (v: number) => number {
  const free = values.reduce((s, v, i) => (fixed.has(i) ? s : s + Math.max(0, v)), 0)
  const room = available - fixed.size * min
  return (v) => (free > 0 ? (Math.max(0, v) / free) * room : room / (values.length - fixed.size))
}

/** Pins every free value whose share is under `min`; true when any was pinned. */
function fixUnderMin(values: readonly number[], fixed: Set<number>, share: (v: number) => number, min: number): boolean {
  let changed = false
  values.forEach((v, i) => {
    if (fixed.has(i) || !(share(v) < min)) return
    fixed.add(i)
    changed = true
  })
  return changed
}

export function layoutPhaseBlocks(phases: readonly PhaseBlockInput[], dims: PhaseBlocksDims = PHASE_BLOCKS): PhaseBlocksLayout {
  const n = phases.length
  const durations = phases.map((p) => (p.durationMs && p.durationMs > 0 ? p.durationMs : 0))
  const totalMs = durations.reduce((s, v) => s + v, 0)
  const maxTokens = phases.reduce((m, p) => Math.max(m, p.tokens ?? 0), 0)
  const available = dims.width - dims.left - dims.right - dims.dx - dims.gap * Math.max(0, n - 1)
  const widths = shareWidths(durations, available, dims.minWidth)
  let x = dims.left
  const blocks: PhaseBlock[] = phases.map((p, i) => {
    const width = widths[i]!
    const tokens = p.tokens ?? 0
    const height = maxTokens > 0 && tokens > 0 ? Math.max(dims.minHeight, Math.round((tokens / maxTokens) * dims.maxHeight)) : dims.minHeight
    const paths = obliqueBox({ x, y: dims.ground, width, height, dx: dims.dx, dy: dims.dy })
    // Labels may run into the gap and under the next block's depth offset.
    const room = width + dims.gap + (i === n - 1 ? dims.dx + dims.right : 0) - 4
    const text = String(i + 1).padStart(2, '0')
    const number = width >= 26 && height >= 18 ? { x: round2(x + 10), y: dims.ground - 9, text } : null
    const metaText = fitLabel([p.meta, p.metaShort], room, dims.metaCharWidth)
    const block: PhaseBlock = {
      index: i,
      name: p.name,
      tone: p.tone ?? 'done',
      x: round2(x),
      width,
      height,
      paths,
      number,
      label: { x: round2(x), y: dims.ground + 24, text: fitLabel([p.name], room, dims.nameCharWidth) },
      meta: metaText ? { x: round2(x), y: dims.ground + 42, text: metaText } : null,
    }
    x = round1(x + width + dims.gap)
    return block
  })
  return { viewBox: `0 0 ${dims.width} ${dims.height}`, blocks, totalMs, maxTokens }
}
