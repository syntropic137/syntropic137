/**
 * "Needs a look" chips the viewer has opened (feedback 443e9c0a): hidden on
 * return, with a muted "N seen · show" to reveal them. A run is seen at one
 * failure: its id plus when that failure finished, so a run that fails again
 * later (a resume, a retry) has a new signature and comes back.
 */
import type { OverviewRunInput } from './overview'

/** localStorage key for the viewer's seen signatures (a per-viewer convenience). */
export const SEEN_RUNS_STORAGE_KEY = 'syn-ui:overview:seen-runs'

/** How many signatures to remember; the oldest drop off first. */
export const SEEN_RUNS_MAX = 200

/** The failure the viewer saw: run id and the time it ended (or started, while it has no end). */
export function seenSignature(run: Pick<OverviewRunInput, 'workflow_execution_id' | 'started_at' | 'completed_at'>): string {
  return `${run.workflow_execution_id}@${run.completed_at ?? run.started_at ?? ''}`
}

/** Stored JSON back to signatures; anything malformed is an empty list. */
export function parseSeenRuns(raw: string | null | undefined): string[] {
  if (!raw) return []
  try {
    const v: unknown = JSON.parse(raw)
    return Array.isArray(v) ? v.filter((s): s is string => typeof s === 'string') : []
  } catch {
    return []
  }
}

/** Add a signature (newest last), deduped, capped at `max`. */
export function markSeen(seen: readonly string[], signature: string, max = SEEN_RUNS_MAX): string[] {
  const out = seen.filter((s) => s !== signature)
  out.push(signature)
  return out.slice(Math.max(0, out.length - max))
}

/** Split attention runs into the ones still to look at and the ones already seen, order kept. */
export function splitSeenRuns<T extends OverviewRunInput>(runs: readonly T[], seen: readonly string[]): { fresh: T[]; seen: T[] } {
  const set = new Set(seen)
  const fresh: T[] = []
  const old: T[] = []
  for (const r of runs) (set.has(seenSignature(r)) ? old : fresh).push(r)
  return { fresh, seen: old }
}

/** The muted toggle: "2 seen · show" or "2 seen · hide". */
export function seenToggleLabel(count: number, showing: boolean): string {
  return `${count} seen · ${showing ? 'hide' : 'show'}`
}
