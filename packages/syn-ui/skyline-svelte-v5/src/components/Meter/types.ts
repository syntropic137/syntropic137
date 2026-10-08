import type { HTMLAttributes } from 'svelte/elements'
import type { MeterContract } from '@syn137/skyline-core/contracts'

/** Bar colour by series, for meters that stand for a token type or an agent. */
export type MeterSeries = 'data-1' | 'data-2' | 'data-3' | 'data-4' | 'claude' | 'codex'

/**
 * Meter (MeterContract). CompDisplay "meter": a name and a mono figure over
 * a 6px bar, for most-run workflows, cost by model and usage bars.
 *
 * Colour: `series` wins, then `tone`. Without either, `low` / `high` /
 * `optimum` work as on the HTML <meter>: a value outside the optimum's
 * region turns the bar amber.
 */
export interface MeterProps extends MeterContract, Omit<HTMLAttributes<HTMLDivElement>, keyof MeterContract | 'children'> {
  /** Visible name on the left; also the accessible name. */
  label?: string
  /** Skyline: HTML <meter> regions (upstream MeterContract has none). */
  low?: number
  high?: number
  optimum?: number
  /** Figure on the right, e.g. "26 runs". Also used as aria-valuetext. */
  valueText?: string
  series?: MeterSeries
}
