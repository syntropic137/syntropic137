import type { SkylineDay } from '@syn137/skyline-core/geometry'
import type { HTMLAttributes } from 'svelte/elements'

export interface DayReadoutProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children'> {
  day: SkylineDay | null
  /**
   * `dock`: the fixed desktop readout beside the Skyline (no stepper).
   * `card`: the phone card under the chart, with 44px previous and next buttons.
   */
  variant?: 'dock' | 'card'
  /** "11 of 11 active days" (card variant). */
  position?: string
  onprev?: () => void
  onnext?: () => void
  /** Link to the runs of that day. */
  runsHref?: string
}
