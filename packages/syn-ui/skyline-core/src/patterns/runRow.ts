/**
 * Run Row (Main, Executions, Workflow boards): status, name, a bar whose
 * length is duration and whose blocks are phases, then tokens, cost and age.
 */
import { statusKind, type StatusKind } from './status'

export type RunSegmentTone = 'done' | 'failed' | 'cancelled' | 'running' | 'empty'

export interface RunRowProps {
  /** Raw API status; mapped once by statusSemantics(). */
  status: string
  name: string
  /** Skyline: a small marker after the name, such as "Eval" for a run that belongs to an eval (evalBadge()). */
  tag?: { label: string; title?: string } | null
  /** Mono line under the name; build it with runSubline() when you have repo and phase counts. */
  sub?: string
  href?: string
  /** Phase blocks, oldest first. Build with runSegments(). */
  segments: readonly RunSegmentTone[]
  /** Duration rule length as a percentage of the track; runBarPercent(). */
  barPercent: number
  /**
   * Skyline: phase columns shared by every row in the list (runSlots()), so
   * phase N sits in the same column on every row. Defaults to this row's
   * segment count.
   */
  slots?: number
  duration: string
  tokens?: string
  cost?: string
  when?: string
}

export interface RunSegmentsInput {
  status: string
  /** Completed phases. */
  done: number
  total: number
}

/**
 * Phase blocks for a run: completed phases fill with the accent, the phase
 * where the run stopped takes the outcome (coral for failed, grey for
 * cancelled, pulsing for running), the rest stay empty.
 */
export function runSegments({ status, done, total }: RunSegmentsInput): RunSegmentTone[] {
  const stop = STOP_TONE[statusKind(status)] ?? 'empty'
  const n = Math.max(0, Math.floor(total))
  const k = Math.max(0, Math.min(n, Math.floor(done)))
  const out: RunSegmentTone[] = []
  for (let i = 0; i < n; i++) out.push(segmentTone(i, k, stop))
  return out
}

/** Tone of the segment where the run stopped, by status kind; other kinds leave it empty. */
const STOP_TONE: Partial<Record<StatusKind, RunSegmentTone>> = {
  failed: 'failed',
  cancelled: 'cancelled',
  interrupted: 'cancelled',
  running: 'running',
}

function segmentTone(i: number, done: number, stop: RunSegmentTone): RunSegmentTone {
  if (i < done) return 'done'
  return i === done ? stop : 'empty'
}

/** Duration against the longest run in view, floored so a 3s run still shows: 227 of 227 -> 100. */
export function runBarPercent(durationMs: number | null | undefined, longestMs: number | null | undefined, min = 4): number {
  if (!durationMs || !longestMs || longestMs <= 0 || durationMs <= 0) return min
  return Math.max(min, Math.min(100, Math.round((durationMs / longestMs) * 100)))
}

/**
 * Shared phase grid for a list: the most phases any row has (at least 1).
 * Every row lays its blocks on this many equal columns, so blocks are one
 * size and line up across rows whatever each run's duration (feedback
 * c80ad278: duration-scaled fills made 8 phases of a 1m run into slivers).
 */
export function runSlots(totals: readonly (number | null | undefined)[]): number {
  return totals.reduce<number>((m, t) => Math.max(m, Math.floor(t ?? 0)), 1)
}

/** Columns a row's phase grid uses: the list's slots, widened if this row has more segments. */
export function runBarColumns(segments: number, slots: number | null | undefined): number {
  return Math.max(1, Math.floor(segments), Math.floor(slots ?? 0))
}

/** "syntropic137/syntropic137 · 0 of 2 phases"; `compact` gives "0/2 phases" (phone). */
export function runSubline(repo: string | null | undefined, done: number, total: number, compact = false): string {
  const phases = compact ? `${done}/${total} ${total === 1 ? 'phase' : 'phases'}` : `${done} of ${total} ${total === 1 ? 'phase' : 'phases'}`
  return `${repo || 'no repo'} · ${phases}`
}
