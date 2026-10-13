/**
 * IsoCity keyboard (codex review of #1856): what a key means, as data, so
 * the component's handler stays a dispatch. On a day, Left and Right step
 * active days; elsewhere in the chart they scroll a month (Left is back in
 * time). Page Up and Page Down scroll a month, Home goes to the oldest
 * window, End to now. Anything else is not ours (null).
 */
export type IsoCityKeyIntent = { kind: 'step'; dir: 1 | -1 } | { kind: 'offset'; offset: number }

export interface IsoCityKeyContext {
  /** The key went to a day button (not the chart itself). */
  onDay: boolean
  /** Months back now, and the most there is. */
  offset: number
  maxOffset: number
}

const MONTH_KEYS: Readonly<Record<string, number>> = { ArrowLeft: 1, PageUp: 1, ArrowRight: -1, PageDown: -1 }
const DAY_KEYS: Readonly<Record<string, 1 | -1>> = { ArrowLeft: -1, ArrowRight: 1 }

const clamp = (n: number, max: number) => Math.min(max, Math.max(0, n))

export function isoCityKeyIntent(key: string, ctx: IsoCityKeyContext): IsoCityKeyIntent | null {
  const dir = DAY_KEYS[key]
  if (ctx.onDay && dir !== undefined) return { kind: 'step', dir }
  const months = MONTH_KEYS[key]
  if (months !== undefined) return { kind: 'offset', offset: clamp(ctx.offset + months, ctx.maxOffset) }
  if (key === 'End') return { kind: 'offset', offset: 0 }
  if (key === 'Home') return { kind: 'offset', offset: ctx.maxOffset }
  return null
}

/**
 * Roving focus target (codex review of #1856): the one visible day that
 * takes Tab, kept apart from the selection. The selected day when it is in
 * view, otherwise the visible day nearest to it in time (the newest visible
 * day when nothing is selected), otherwise null.
 */
export function isoCityRovingDate(visible: readonly string[], preferred: string | null | undefined): string | null {
  if (visible.length === 0) return null
  if (!preferred) return [...visible].sort().at(-1)!
  if (visible.includes(preferred)) return preferred
  let best = visible[0]!
  let gap = Infinity
  for (const d of visible) {
    const g = Math.abs(Date.parse(d) - Date.parse(preferred))
    if (g < gap || (g === gap && d > best)) {
      best = d
      gap = g
    }
  }
  return best
}
