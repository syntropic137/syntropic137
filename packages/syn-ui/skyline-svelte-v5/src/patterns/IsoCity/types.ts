import type { IsoCityCoverage, SkylineDay } from '@syn137/skyline-core/geometry'
import type { HTMLAttributes } from 'svelte/elements'

/** The weeks the window shows, as Mondays and the Sunday of the last week. */
export interface IsoCityWindow {
  start: string
  end: string
  /** Week index of the first week shown in the history (0 = oldest). */
  first: number
}

export interface IsoCityProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children' | 'onselect'> {
  /** Per-day series (any order); days missing from it are empty floor tiles. */
  days: readonly SkylineDay[]
  /** ISO day; later days draw as future outlines. Defaults to today (UTC). */
  today?: string
  /** Weeks of history in the week strip (default 52). */
  history?: number
  /** Weeks shown; defaults to the board's 14 (wide) or 8 (narrow). */
  window?: number
  /** Months back (0 = latest). Bindable. */
  offset?: number
  /** Selected day (ISO). Bindable; defaults to the latest active day. */
  selected?: string | null
  onselect?: (day: SkylineDay) => void
  /** Called whenever the window moves, so the page can load older weeks. */
  onwindow?: (w: IsoCityWindow) => void
  /** Link for "Runs →" in the readout. */
  runsHref?: (day: SkylineDay) => string
  /** Container width in px from which the desktop board is used. Default 720. */
  wideFrom?: number
  /** Optional chip after the range ("Sample history" in fixtures and stories). */
  badge?: string
  /**
   * How much of the history `days` covers. Weeks before `coverage.from` are
   * unknown, not zero (strip and floor say so); `state` 'error' shows a
   * Retry that calls `onretry`. Null or absent: `days` is the whole history.
   */
  coverage?: IsoCityCoverage | null
  onretry?: () => void
}
