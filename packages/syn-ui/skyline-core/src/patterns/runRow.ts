/**
 * Run Row (Main, Executions, Workflow boards): status, name, a bar whose
 * length is duration and whose blocks are phases, then tokens, cost and age.
 */
import { statusKind } from './status'

export type RunSegmentTone = 'done' | 'failed' | 'cancelled' | 'running' | 'empty'

export interface RunRowProps {
  /** Raw API status; mapped once by statusSemantics(). */
  status: string
  name: string
  /** Mono line under the name; build it with runSubline() when you have repo and phase counts. */
  sub?: string
  href?: string
  /** Phase blocks, oldest first. Build with runSegments(). */
  segments: readonly RunSegmentTone[]
  /** Bar length as a percentage of the track; runBarPercent(). */
  barPercent: number
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
  const kind = statusKind(status)
  const n = Math.max(0, Math.floor(total))
  const k = Math.max(0, Math.min(n, Math.floor(done)))
  const out: RunSegmentTone[] = []
  for (let i = 0; i < n; i++) {
    if (i < k) out.push('done')
    else if (i === k && kind === 'failed') out.push('failed')
    else if (i === k && (kind === 'cancelled' || kind === 'interrupted')) out.push('cancelled')
    else if (i === k && kind === 'running') out.push('running')
    else out.push('empty')
  }
  return out
}

/** Duration against the longest run in view, floored so a 3s run still shows: 227 of 227 -> 100. */
export function runBarPercent(durationMs: number | null | undefined, longestMs: number | null | undefined, min = 4): number {
  if (!durationMs || !longestMs || longestMs <= 0 || durationMs <= 0) return min
  return Math.max(min, Math.min(100, Math.round((durationMs / longestMs) * 100)))
}

/** "syntropic137/syntropic137 · 0 of 2 phases"; `compact` gives "0/2 phases" (phone). */
export function runSubline(repo: string | null | undefined, done: number, total: number, compact = false): string {
  const phases = compact ? `${done}/${total} ${total === 1 ? 'phase' : 'phases'}` : `${done} of ${total} ${total === 1 ? 'phase' : 'phases'}`
  return `${repo || 'no repo'} · ${phases}`
}
