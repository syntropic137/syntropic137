/**
 * Verdict counts (PASS, FAIL, ERROR, unscored) for an eval and each of its
 * variants, counted from the eval's run history.
 *
 * The API reports no per-verdict counts, so they come from the runs. That only
 * holds when the history read covers EVERY run: a history cut short (by the
 * timeline's bound, or a run added between pages) would undercount. Then, and
 * when a variant's runs do not add up to the server's run count for it, the
 * counts are unavailable (null) rather than guessed from a rounded pass rate.
 */

import type { EvalRun, EvalSummary, EvalVariant } from '../api/evals'
import type { EvalTimelineState } from '../hooks/useEvalTimeline'
import { variantKey } from './evalVariants'

export interface VerdictCounts {
  pass: number
  fail: number
  error: number
  unscored: number
}

/** The eval's counts, and each variant's keyed by `variantKey`; null where unavailable. */
export interface EvalVerdictCounts {
  eval: VerdictCounts | null
  byVariant: ReadonlyMap<string, VerdictCounts> | null
}

const UNAVAILABLE: EvalVerdictCounts = { eval: null, byVariant: null }

function emptyCounts(): VerdictCounts {
  return { pass: 0, fail: 0, error: 0, unscored: 0 }
}

function add(counts: VerdictCounts, run: EvalRun): void {
  if (run.verdict === 'PASS') counts.pass++
  else if (run.verdict === 'FAIL') counts.fail++
  else if (run.verdict === 'ERROR') counts.error++
  else counts.unscored++
}

function totalOf(c: VerdictCounts): number {
  return c.pass + c.fail + c.error + c.unscored
}

/** The variant a run belongs to, in the same key the server's variants get. */
function runKey(run: EvalRun): string {
  const models = [...new Set(run.models.map((m) => m.model))].sort()
  return variantKey({ workflow_id: run.workflow_id, workflow_version: run.workflow_version ?? null, models })
}

/** "2 PASS · 1 FAIL · 1 ERROR · 4 unscored": every population, zeros included. */
export function verdictBreakdown(c: VerdictCounts): string {
  return `${c.pass} PASS · ${c.fail} FAIL · ${c.error} ERROR · ${c.unscored} unscored`
}

/** Each variant's counts, or null unless the runs group into exactly the server's variants and sizes. */
function countByVariant(runs: readonly EvalRun[], variants: readonly EvalVariant[]): ReadonlyMap<string, VerdictCounts> | null {
  const byVariant = new Map<string, VerdictCounts>()
  for (const run of runs) {
    const key = runKey(run)
    const counts = byVariant.get(key) ?? emptyCounts()
    add(counts, run)
    byVariant.set(key, counts)
  }
  const consistent =
    byVariant.size === variants.length && variants.every((v) => totalOf(byVariant.get(variantKey(v)) ?? emptyCounts()) === v.run_count)
  return consistent ? byVariant : null
}

/**
 * Counts over the whole eval and per variant. Both are null unless the history
 * is complete: ready, and as long as both its own total and the eval's run
 * count. The per-variant counts are also null when the runs do not group into
 * the server's variants (an API with no variants, or a grouping that drifted).
 */
export function evalVerdictCounts(timeline: EvalTimelineState, e: EvalSummary): EvalVerdictCounts {
  if (timeline.kind !== 'ready') return UNAVAILABLE
  const { runs } = timeline
  if (runs.length !== timeline.total || runs.length !== e.run_count) return UNAVAILABLE
  const all = emptyCounts()
  for (const run of runs) add(all, run)
  return { eval: all, byVariant: countByVariant(runs, e.variants ?? []) }
}
