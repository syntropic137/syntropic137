/**
 * The three coverage states an aggregate cost can be in (#897, #890).
 *
 * `total_cost_display` is what the API renders for each, verbatim: the
 * backend owns the wording, including the ASCII `>=` (metrics.py,
 * workflows/queries.py). `total_cost_usd` is deliberately NOT the figure the
 * display carries, so a surface that formats the dollars itself again shows
 * `$1.2500` or `$0.0000` and cannot pass.
 *
 * The three cost fields are typed from the GENERATED wire schema, so
 * `total_cost_usd` is the decimal string the API actually sends.
 */
import type { components } from '../generated/api-types'

export type CostCoverageWire = Pick<
  components['schemas']['MetricsResponse'],
  'total_cost_usd' | 'total_cost_display' | 'unpriced_observation_count'
>

export interface CostCoverageCase extends CostCoverageWire {
  name: string
  /** Text the surface must show for the cost. */
  shows: string
  /** The coverage note, or null when everything was priced. */
  note: RegExp | null
}

export const COST_COVERAGE_CASES: CostCoverageCase[] = [
  {
    name: 'partial',
    total_cost_usd: '1.25',
    total_cost_display: '>=$1.25 (partial)',
    unpriced_observation_count: 3,
    shows: '>=$1.25 (partial)',
    note: /3 unpriced observations/,
  },
  {
    name: 'unpriced',
    total_cost_usd: '0',
    total_cost_display: 'unpriced',
    unpriced_observation_count: 2,
    shows: 'unpriced',
    note: /2 unpriced observations/,
  },
  {
    name: 'fully priced',
    total_cost_usd: '1.25',
    total_cost_display: '$1.25',
    unpriced_observation_count: 0,
    shows: '$1.25',
    note: null,
  },
]

/** Any coverage note at all, for asserting there is none. */
export const ANY_UNPRICED_NOTE = /unpriced observation/

/**
 * A fully priced sub-cent total. The API rounds it to the payable unit; a
 * client formatting the dollars itself prints `$0.004000` instead, so this is
 * the case that catches a fully priced figure re-formatted on the client.
 */
export const SUB_CENT_CASE: CostCoverageCase = {
  name: 'priced below a cent',
  total_cost_usd: '0.004',
  total_cost_display: '<$0.01',
  unpriced_observation_count: 0,
  shows: '<$0.01',
  note: null,
}
