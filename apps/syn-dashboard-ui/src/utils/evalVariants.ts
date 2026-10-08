/**
 * Ordering the Compare table's variants, and deciding which one is best.
 *
 * Every figure here is the server's (computed over all of an eval's runs);
 * this module only orders rows by them, so it never formats or recomputes one.
 */

import type { EvalVariant } from '../api/evals'

export type VariantSortKey = 'pass_rate' | 'runs' | 'duration' | 'cost' | 'last_run'
export type VariantSortDir = 'asc' | 'desc'

/** The server's grouping key, so two versions of one workflow never share a React key. */
export function variantKey(v: EvalVariant): string {
  return `${v.workflow_id}|${v.workflow_version ?? ''}|${v.models.join(',')}`
}

const SORT_VALUE: Record<VariantSortKey, (v: EvalVariant) => number | null> = {
  pass_rate: (v) => v.pass_rate,
  runs: (v) => v.run_count,
  duration: (v) => v.stats.median_duration_seconds,
  cost: (v) => (v.stats.median_cost_usd === null ? null : Number(v.stats.median_cost_usd)),
  last_run: (v) => (v.last_run_at ? Date.parse(v.last_run_at) : null),
}

/** Sorted copy. A variant with no figure for the key (nothing judged, no cost known) always sorts last. */
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

/**
 * The variant to beat: highest pass rate, then the cheaper median run, then
 * more runs behind the figure. Null unless at least two variants have a pass
 * rate - "best" of one is not a comparison, and ERROR/unscored runs give none.
 */
export function bestVariantKey(variants: readonly EvalVariant[]): string | null {
  const judged = variants.filter((v) => v.pass_rate !== null)
  if (judged.length < 2) return null
  const cost = (v: EvalVariant) => (v.stats.median_cost_usd === null ? Infinity : Number(v.stats.median_cost_usd))
  const [best] = [...judged].sort(
    (a, b) => (b.pass_rate ?? 0) - (a.pass_rate ?? 0) || cost(a) - cost(b) || b.run_count - a.run_count,
  )
  return variantKey(best)
}
