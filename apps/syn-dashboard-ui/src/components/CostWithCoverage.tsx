/**
 * An aggregate cost as the API rendered it, and whether it is complete (#897).
 *
 * `display` is the backend's `total_cost_display` (`$1.25`,
 * `>=$1.25 (partial)`, `unpriced`), shown verbatim: the coverage rules live in
 * `syn_shared.display`, so this never formats dollars from `total_cost_usd`.
 * When `unpricedObservationCount` is non-zero the total omits real work, and a
 * note says how much, so a partial figure is not read as the whole (#890).
 *
 * Renders inline (spans only) so it can sit in a MetricCard subtitle or a row.
 */

interface CostWithCoverageProps {
  /** `total_cost_display` from the same response. */
  display: string
  /** `unpriced_observation_count` from the same response. */
  unpricedObservationCount: number
}

export function CostWithCoverage({ display, unpricedObservationCount }: CostWithCoverageProps) {
  return (
    <>
      <span>{display}</span>
      {unpricedObservationCount > 0 && (
        <span className="ml-1 text-amber-400">
          ({unpricedObservationCount} unpriced observation{unpricedObservationCount === 1 ? '' : 's'} not
          in total)
        </span>
      )}
    </>
  )
}
