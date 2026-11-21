/**
 * The three coverage states an aggregate cost can be in (#897, #890).
 *
 * `total_cost_display` is what the API renders for each, verbatim: the
 * backend owns the wording, including the ASCII `>=` (metrics.py,
 * workflows/queries.py). `total_cost_usd` is deliberately NOT the figure the
 * display carries, so a surface that formats the dollars itself again shows
 * `$1.2500` or `$0.0000` and cannot pass.
 */
export interface CostCoverageCase {
  name: string
  total_cost_usd: number
  total_cost_display: string
  unpriced_observation_count: number
  /** Text the surface must show for the cost. */
  shows: string
  /** The coverage note, or null when everything was priced. */
  note: RegExp | null
}

export const COST_COVERAGE_CASES: CostCoverageCase[] = [
  {
    name: 'partial',
    total_cost_usd: 1.25,
    total_cost_display: '>=$1.25 (partial)',
    unpriced_observation_count: 3,
    shows: '>=$1.25 (partial)',
    note: /3 unpriced observations/,
  },
  {
    name: 'unpriced',
    total_cost_usd: 0,
    total_cost_display: 'unpriced',
    unpriced_observation_count: 2,
    shows: 'unpriced',
    note: /2 unpriced observations/,
  },
  {
    name: 'fully priced',
    total_cost_usd: 1.25,
    total_cost_display: '$1.25',
    unpriced_observation_count: 0,
    shows: '$1.25',
    note: null,
  },
]

/** Any coverage note at all, for asserting there is none. */
export const ANY_UNPRICED_NOTE = /unpriced observation/
