import type { SkylineDay } from '@syn137/skyline-core/geometry'
import type { HTMLAttributes } from 'svelte/elements'

export interface SkylineProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children' | 'onselect'> {
  days: readonly SkylineDay[]
  /** ISO day; later days draw as future tiles. Defaults to today (UTC). */
  today?: string
  /** Year shown on desktop and by the phone's Year toggle. Defaults to the year of `today`. */
  year?: number
  /** Years offered by the year toggle (desktop). Hidden with fewer than two. */
  years?: readonly number[]
  onyearchange?: (year: number) => void
  /** Selected day (ISO). Bindable; defaults to the latest active day. */
  selected?: string | null
  onselect?: (day: SkylineDay) => void
  /** Link for "Runs →" in the readout. */
  runsHref?: (day: SkylineDay) => string
  /** Container width in px from which the desktop layout (full year, docked readout) is used. Default 720. */
  wideFrom?: number
}
