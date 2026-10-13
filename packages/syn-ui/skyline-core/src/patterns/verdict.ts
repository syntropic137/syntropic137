/**
 * Verdict Board (Evals board): cases down the side, verifiers across, one
 * verdict block per cell, bugs caught and average cost per verifier.
 */
import { formatCost } from '../format/cost'
import { formatDuration } from '../format/duration'
import type { Verdict } from '../geometry/verdictBlock'

export type { Verdict } from '../geometry/verdictBlock'

export type VerdictTone = 'accent' | 'danger' | 'warning' | 'unscored'

export interface VerdictLook {
  /** Pill text: "Pass", "Fail", "Error", "Unscored". */
  word: string
  /** Legend and accessible text: "Scorer error". */
  label: string
  tone: VerdictTone
}

export const VERDICT_LOOK: Record<Verdict, VerdictLook> = {
  pass: { word: 'Pass', label: 'Pass', tone: 'accent' },
  fail: { word: 'Fail', label: 'Fail', tone: 'danger' },
  error: { word: 'Error', label: 'Scorer error', tone: 'warning' },
  unscored: { word: 'Unscored', label: 'Unscored', tone: 'unscored' },
}

const VERDICT_WORDS: Record<string, Verdict> = {
  pass: 'pass',
  passed: 'pass',
  success: 'pass',
  fail: 'fail',
  failed: 'fail',
  failure: 'fail',
  error: 'error',
  errored: 'error',
  scorer_error: 'error',
}

/** API verdict strings ("PASS", "passed", "scorer_error", null) -> a Verdict. */
export function normalizeVerdict(raw: string | boolean | null | undefined): Verdict {
  if (raw === true) return 'pass'
  if (raw === false) return 'fail'
  const key = (raw ?? '').toString().toLowerCase()
  return Object.hasOwn(VERDICT_WORDS, key) ? (VERDICT_WORDS[key] ?? 'unscored') : 'unscored'
}

export interface VerdictCase {
  id: string
  /** Mono case name: "shared-esp-stream". */
  name: string
  /** "PR #1574 · 6646da2". */
  sub?: string
}

export interface Verifier {
  id: string
  /** "Claude", "Codex". */
  agent: string
  agentKind?: 'claude' | 'codex' | 'other'
  /** "claude-opus-5-5". */
  model: string
  /** Column head on a phone: "opus". */
  short?: string
  /** Workflow the verifier runs: "eval-verify-pinned-v1". */
  workflow?: string
}

export interface VerdictCell {
  verdict: Verdict
  costUsd?: number | null
  durationMs?: number | null
  /** "Oct 2, 2026". */
  date?: string
  evidence?: string
  /** Eval detail and run links for the readout. */
  evalHref?: string
  runHref?: string
  runs?: number
}

/** Cells are keyed `${caseId}:${verifierId}`. */
export type VerdictMatrix = Record<string, VerdictCell | undefined>

export const cellKey = (caseId: string, verifierId: string) => `${caseId}:${verifierId}`

export interface VerifierFooter {
  /** "5/6", or an em dash when nothing is scored. */
  fraction: string
  scored: boolean
  /** Bar fill: passes over cases, 0..100. */
  fill: number
  /** "caught", "caught · 1 scorer error", "not scored yet". */
  note: string
  /** "$1.08 · 6m 11s". */
  averages: string
}

export function verifierFooter(cells: readonly (VerdictCell | undefined)[]): VerifierFooter {
  const present = cells.filter((c): c is VerdictCell => !!c)
  const n = cells.length
  const pass = present.filter((c) => c.verdict === 'pass').length
  const scored = present.filter((c) => c.verdict !== 'unscored').length
  const errors = present.filter((c) => c.verdict === 'error').length
  const costs = present.map((c) => c.costUsd).filter((v): v is number => typeof v === 'number')
  const durs = present.map((c) => c.durationMs).filter((v): v is number => typeof v === 'number')
  const avg = (xs: number[]) => (xs.length ? xs.reduce((s, v) => s + v, 0) / xs.length : null)
  const cost = avg(costs)
  const dur = avg(durs)
  return {
    fraction: scored === 0 ? '—' : `${pass}/${n}`,
    scored: scored > 0,
    fill: n > 0 ? Math.round((pass / n) * 100) : 0,
    note: scored === 0 ? 'not scored yet' : errors > 0 ? `caught · ${errors} scorer ${errors === 1 ? 'error' : 'errors'}` : 'caught',
    averages: `${cost === null ? '—' : formatCost(cost)} · ${dur === null ? '—' : formatDuration(dur)}`,
  }
}

/** "codex-cost-limit under gpt-5.6-sol: Pass, $0.49". */
export function verdictCellLabel(c: VerdictCase, v: Verifier, cell: VerdictCell | undefined): string {
  if (!cell) return `${c.name} under ${v.model}: no run`
  const cost = typeof cell.costUsd === 'number' ? `, ${formatCost(cell.costUsd)}` : ''
  return `${c.name} under ${v.model}: ${VERDICT_LOOK[cell.verdict].label}${cost}`
}
