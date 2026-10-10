import type { BadgeVariant, ContractTone } from '../contracts'

/**
 * Status -> badge semantics, decided once (spec: "Variants map to meaning
 * once"). Screens pass a raw API status; they never pick colours.
 */
export type StatusKind = 'completed' | 'failed' | 'refused' | 'cancelled' | 'running' | 'pending' | 'interrupted' | 'skipped' | 'unknown'

/** Glyph names the Status Badge pattern draws. */
export type StatusGlyph = 'check' | 'cross' | 'dash' | 'spinner' | 'clock' | 'pause' | 'skip' | 'dot'

export interface StatusSemantics {
  kind: StatusKind
  label: string
  variant: BadgeVariant
  tone: ContractTone
  glyph: StatusGlyph
  /** Animates (spinner, pulsing block) unless reduced motion. */
  live: boolean
  /** No further change expected. */
  terminal: boolean
  /** The state's colour, a `--sky-status-*` token; glyphs, segments and dots use it. */
  token: string
}

const TABLE: Record<StatusKind, Omit<StatusSemantics, 'kind' | 'token'>> = {
  completed: { label: 'Completed', variant: 'soft', tone: 'success', glyph: 'check', live: false, terminal: true },
  failed: { label: 'Failed', variant: 'soft', tone: 'danger', glyph: 'cross', live: false, terminal: true },
  // A correct refusal (#1357): the agent judged the work should not be done and the platform recorded it. Amber, not red: nothing broke.
  refused: { label: 'Refused', variant: 'soft', tone: 'warning', glyph: 'dash', live: false, terminal: true },
  cancelled: { label: 'Cancelled', variant: 'outline', tone: 'neutral', glyph: 'dash', live: false, terminal: true },
  interrupted: { label: 'Interrupted', variant: 'outline', tone: 'warning', glyph: 'pause', live: false, terminal: true },
  running: { label: 'Running', variant: 'soft', tone: 'accent', glyph: 'spinner', live: true, terminal: false },
  pending: { label: 'Pending', variant: 'outline', tone: 'neutral', glyph: 'clock', live: false, terminal: false },
  skipped: { label: 'Skipped', variant: 'outline', tone: 'neutral', glyph: 'skip', live: false, terminal: true },
  unknown: { label: 'Unknown', variant: 'outline', tone: 'neutral', glyph: 'dot', live: false, terminal: false },
}

/** The colour token for a status kind (themes/src/tokens.css). */
export function statusToken(kind: StatusKind): string {
  return `var(--sky-status-${kind})`
}

const ALIASES: Record<string, StatusKind> = {
  completed: 'completed',
  succeeded: 'completed',
  success: 'completed',
  passed: 'completed',
  failed: 'failed',
  error: 'failed',
  refused: 'refused',
  correct_refusal: 'refused',
  cancelled: 'cancelled',
  canceled: 'cancelled',
  interrupted: 'interrupted',
  running: 'running',
  in_progress: 'running',
  started: 'running',
  active: 'running',
  pending: 'pending',
  queued: 'pending',
  not_started: 'pending',
  skipped: 'skipped',
}

export function statusKind(status: string | null | undefined): StatusKind {
  if (!status) return 'unknown'
  return ALIASES[status.toLowerCase()] ?? 'unknown'
}

/**
 * Badge semantics for an API status. `queued` keeps its own label though it
 * reads as pending; an unrecognised status shows its raw text, neutral.
 */
export function statusSemantics(status: string | null | undefined): StatusSemantics {
  const kind = statusKind(status)
  const base = TABLE[kind]
  let label = base.label
  if (kind === 'unknown' && status) label = humanize(status)
  else if (status?.toLowerCase() === 'queued') label = 'Queued'
  return { kind, ...base, label, token: statusToken(kind) }
}

/**
 * The status to draw for a run: `failed` with `failure_classification`
 * `correct_refusal` reads as `refused` (the React dashboard's outcomeTone);
 * every other pair keeps its status, so an unclassified failure stays red.
 */
export function outcomeStatus(status: string, failureClassification?: string | null): string {
  return status.toLowerCase() === 'failed' && failureClassification === 'correct_refusal' ? 'refused' : status
}

/** "not_started" -> "Not started". */
export function humanize(value: string): string {
  const s = value.replace(/[_-]+/g, ' ').trim()
  return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase()
}
