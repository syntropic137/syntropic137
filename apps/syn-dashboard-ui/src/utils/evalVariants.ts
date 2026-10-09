/**
 * Ordering the Compare table's variants, and deciding which one is best.
 *
 * Every figure here is the server's (computed over all of an eval's runs);
 * this module only orders rows by them, so it never formats or recomputes one.
 */

import type { EvalVariant } from '../api/evals'
import type { VerdictCounts } from './evalVerdictCounts'

export type VariantSortKey = 'pass_rate' | 'runs' | 'duration' | 'cost' | 'last_run'
export type VariantSortDir = 'asc' | 'desc'

/** The server's grouping key, so two versions of one workflow never share a React key. */
export function variantKey(v: Pick<EvalVariant, 'workflow_id' | 'workflow_version' | 'models'>): string {
  return `${v.workflow_id}|${v.workflow_version ?? ''}|${v.models.join(',')}`
}

const SORT_VALUE: Record<VariantSortKey, (v: EvalVariant) => number | null> = {
  pass_rate: (v) => v.pass_rate,
  runs: (v) => v.run_count,
  duration: (v) => v.stats?.median_duration_seconds ?? null,
  cost: (v) => (v.stats?.median_cost_usd == null ? null : Number(v.stats.median_cost_usd)),
  last_run: (v) => (v.last_run_at ? Date.parse(v.last_run_at) : null),
}

/**
 * Sorted copy. A variant with no figure for the key (nothing judged, no cost
 * known, or no stats from an older API) always sorts last.
 */
export function sortVariants(variants: readonly EvalVariant[], key: VariantSortKey, dir: VariantSortDir): EvalVariant[] {
  const value = SORT_VALUE[key]
  const sign = dir === 'asc' ? 1 : -1
  return [...variants].sort((a, b) => {
    const x = value(a)
    const y = value(b)
    if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1
    return (x - y) * sign
  })
}

/** Fewer PASS + FAIL runs than this and a pass rate is an anecdote, not a winner. */
export const MIN_JUDGED_FOR_BEST = 3

/** Each variant's verdict counts by `variantKey`; null when the run history does not cover the eval. */
export type VariantCounts = ReadonlyMap<string, VerdictCounts> | null

/** PASS + FAIL behind a variant's pass rate (ERROR and unscored are not judgements); null when the counts are unavailable. */
export function variantJudged(v: EvalVariant, counts: VariantCounts): number | null {
  const c = counts?.get(variantKey(v))
  return c ? c.pass + c.fail : null
}

/** Shown in place of a stats figure when the API sent none (an API older than #1772). */
export const STATS_UNAVAILABLE = 'stats unavailable'

/** Shown in place of a judged count when the run history does not cover every run. */
export const JUDGED_UNAVAILABLE = 'judged count unavailable'

/** The judged sample behind a variant's pass rate, e.g. "4 judged"; null when unknown. */
export function judgedLabel(v: EvalVariant, counts: VariantCounts): string | null {
  const judged = variantJudged(v, counts)
  return judged === null ? null : `${judged} judged`
}

/**
 * The variant to beat: highest pass rate, then the cheaper median run, then
 * more judged runs behind the figure. Only variants with at least
 * MIN_JUDGED_FOR_BEST judged runs compete, so one lucky cheap run cannot win.
 * Null unless at least two compete - "best" of one is not a comparison - and
 * null when the judged counts are unavailable: no sample size, no winner.
 */
export function bestVariantKey(variants: readonly EvalVariant[], counts: VariantCounts): string | null {
  const judged = (v: EvalVariant) => variantJudged(v, counts) ?? 0
  const eligible = variants.filter((v) => v.pass_rate !== null && judged(v) >= MIN_JUDGED_FOR_BEST)
  if (eligible.length < 2) return null
  const cost = (v: EvalVariant) => (v.stats?.median_cost_usd == null ? Infinity : Number(v.stats.median_cost_usd))
  const [best] = [...eligible].sort(
    (a, b) => (b.pass_rate ?? 0) - (a.pass_rate ?? 0) || cost(a) - cost(b) || judged(b) - judged(a),
  )
  return variantKey(best)
}
