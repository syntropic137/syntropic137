/**
 * Live Operations list (feedback 18ec6964): newest first, and rows that
 * arrive while the reader is scrolled down are counted, not jumped to.
 *
 * `liveOps` is a reducer with no timers or DOM: the screen tells it each
 * time the rows change and whether the top of the list is in view, and it
 * answers how many rows are new since the last pass (`added`, for scroll
 * anchoring) and how many the reader has not seen yet (`unseen`, for the
 * "N new" affordance).
 */
import { statusKind } from '../../patterns/status'

/** Rows in display order: newest first. Input is oldest first (sessionOperations). */
export function newestFirst<T>(rows: readonly T[]): T[] {
  return [...rows].reverse()
}

export interface LiveOpsState {
  /** Row ids seen so far; null before the first load. */
  known: ReadonlySet<string> | null
  /** Rows added by the latest `rows` pass. */
  added: number
  /** Rows added while the reader was scrolled away from the top. */
  unseen: number
}

export type LiveOpsEvent =
  /** The rows changed. `atTop`: the top of the list is in view. */
  | { type: 'rows'; ids: readonly string[]; atTop: boolean }
  /** The reader reached the top, or pressed "N new". */
  | { type: 'seen' }

export const LIVE_OPS_INITIAL: LiveOpsState = { known: null, added: 0, unseen: 0 }

export function liveOps(state: LiveOpsState, event: LiveOpsEvent): LiveOpsState {
  if (event.type === 'seen') return state.unseen === 0 && state.added === 0 ? state : { ...state, added: 0, unseen: 0 }
  // First load: everything is the baseline, nothing is "new".
  if (state.known === null) return { known: new Set(event.ids), added: 0, unseen: 0 }
  const known = state.known
  const added = event.ids.reduce((n, id) => (known.has(id) ? n : n + 1), 0)
  if (added === 0) return state.added === 0 ? state : { ...state, added: 0 }
  return { known: new Set([...known, ...event.ids]), added, unseen: event.atTop ? 0 : state.unseen + added }
}

/** "1 new operation", "3 new operations". */
export function unseenLabel(n: number): string {
  return `${n} new ${n === 1 ? 'operation' : 'operations'}`
}

/**
 * How often a session page re-reads while it runs, ms, or null when it
 * need not. The API forwards no per-operation frame for a session (the
 * OperationRecorded payload carries no execution_id, so realtime.py drops
 * it), so a running session polls like the React page does (3 s).
 */
export const RUNNING_SESSION_POLL_MS = 3000
export function sessionPollMs(status: string | null | undefined): number | null {
  return statusKind(status) === 'running' ? RUNNING_SESSION_POLL_MS : null
}
