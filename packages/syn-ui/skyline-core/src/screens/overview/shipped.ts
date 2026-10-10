/**
 * "Shipped by agents" (Main and PhoneOverview boards): five tiles, each a
 * window total, a delta chip against the window before, and a daily bar
 * sparkline. Input is the structural shape of GET /metrics/shipped; this
 * module never imports the data package (ADR-074).
 */
import { formatInteger } from '../../format/number'

export const SHIPPED_TILE_KEYS = ['commits', 'prs_opened', 'prs_merged', 'merge_rate', 'repos_touched'] as const
export type ShippedTileKey = (typeof SHIPPED_TILE_KEYS)[number]

/** Better or worse when the number goes up. Every tile today is up-is-good, merge rate included. */
export type ShippedGoodWhen = 'up' | 'down'

interface TileSpec {
  label: string
  /** `percent` values are 0 to 100 (84 means 84%). */
  unit: 'count' | 'percent'
  goodWhen: ShippedGoodWhen
  /** How the fallback chip reads when the server sends no delta_display. */
  deltaAs: 'relative' | 'absolute' | 'points'
}

export const SHIPPED_TILES: Readonly<Record<ShippedTileKey, TileSpec>> = {
  commits: { label: 'Commits', unit: 'count', goodWhen: 'up', deltaAs: 'relative' },
  prs_opened: { label: 'PRs opened', unit: 'count', goodWhen: 'up', deltaAs: 'relative' },
  prs_merged: { label: 'PRs merged', unit: 'count', goodWhen: 'up', deltaAs: 'relative' },
  merge_rate: { label: 'Merge rate', unit: 'percent', goodWhen: 'up', deltaAs: 'points' },
  repos_touched: { label: 'Repos touched', unit: 'count', goodWhen: 'up', deltaAs: 'absolute' },
}

export interface ShippedPointInput {
  date: string
  value: number | null
}

export interface ShippedMetricInput {
  total: number | null
  previous_total?: number | null
  delta?: number | null
  delta_display?: string | null
  series?: readonly ShippedPointInput[] | null
  reason?: string | null
}

export interface ShippedInput {
  window: { days: number; from: string; to: string }
  commits?: ShippedMetricInput | null
  prs_opened?: ShippedMetricInput | null
  prs_merged?: ShippedMetricInput | null
  merge_rate?: ShippedMetricInput | null
  repos_touched?: ShippedMetricInput | null
  /** Per-tile reasons, when the server sends them beside a null tile. */
  reasons?: Partial<Record<ShippedTileKey, string | null>> | null
}

export type ShippedTone = 'better' | 'worse' | 'flat'

export interface ShippedBar {
  date: string
  value: number
  /** Bar height, percent of the sparkline (4 for an empty day, at least 8 otherwise). */
  height: number
  empty: boolean
  /** The newest day (drawn in full accent). */
  current: boolean
}

export interface ShippedTileAvailable {
  key: ShippedTileKey
  label: string
  available: true
  total: string
  delta: string
  tone: ShippedTone
  bars: ShippedBar[]
  /** Screen-reader sentence: "Commits: 1,204, +38% vs the 14 days before". */
  summary: string
}

export interface ShippedTileUnavailable {
  key: ShippedTileKey
  label: string
  available: false
  reason: string | null
}

export type ShippedTile = ShippedTileAvailable | ShippedTileUnavailable

const DAY_MS = 86_400_000
const EMPTY_HEIGHT = 4
const MIN_HEIGHT = 8

const finite = (n: number | null | undefined): n is number => typeof n === 'number' && Number.isFinite(n)

/** "2026-10-09T00:00:00Z" or "2026-10-09" -> "2026-10-09". */
function dayOf(iso: string): string {
  return iso.slice(0, 10)
}

/** UTC calendar days from `from` to `to` inclusive, oldest first; capped at `days` ending on `to`. */
export function shippedDays(to: string, days: number): string[] {
  const end = Date.parse(`${dayOf(to)}T00:00:00Z`)
  if (!Number.isFinite(end) || days <= 0) return []
  return Array.from({ length: days }, (_, i) => new Date(end - (days - 1 - i) * DAY_MS).toISOString().slice(0, 10))
}

/** One value per day of the window, oldest first; a missing or null day is 0. */
export function normaliseSeries(series: readonly ShippedPointInput[] | null | undefined, to: string, days: number): ShippedPointInput[] {
  const byDay = new Map<string, number>()
  for (const p of series ?? []) if (finite(p.value)) byDay.set(dayOf(p.date), (byDay.get(dayOf(p.date)) ?? 0) + p.value)
  return shippedDays(to, days).map((date) => ({ date, value: byDay.get(date) ?? 0 }))
}

/** Bars scaled to the window's largest day. */
export function shippedBars(points: readonly ShippedPointInput[]): ShippedBar[] {
  const max = Math.max(0, ...points.map((p) => (finite(p.value) ? p.value : 0)))
  return points.map((p, i) => {
    const value = finite(p.value) && p.value > 0 ? p.value : 0
    const empty = value === 0 || max === 0
    return {
      date: p.date,
      value,
      height: empty ? EMPTY_HEIGHT : Math.max(MIN_HEIGHT, Math.round((value / max) * 100)),
      empty,
      current: i === points.length - 1,
    }
  })
}

/** The change, from the server's `delta` or computed from the two totals. Percent tiles change in points. */
export function shippedDelta(m: ShippedMetricInput): number | null {
  if (finite(m.delta)) return m.delta
  return finite(m.total) && finite(m.previous_total) ? m.total - m.previous_total : null
}

/** Better, worse or flat for this tile's direction. */
export function shippedTone(delta: number | null, goodWhen: ShippedGoodWhen): ShippedTone {
  if (delta === null || delta === 0) return 'flat'
  return (delta > 0) === (goodWhen === 'up') ? 'better' : 'worse'
}

/** Rounds half away from zero, so -37.5 reads -38 as +37.5 reads +38. */
const signed = (n: number, suffix: string) => `${n > 0 ? '+' : n < 0 ? '−' : '±'}${Math.round(Math.abs(n))}${suffix}`

/**
 * The chip text. The server's `delta_display` wins (ADR-074 rule 5); without
 * it a relative tile reads "+38%" (or "+3" from zero), an absolute one
 * "+3" and a percent tile "+5 pts".
 */
export function shippedDeltaDisplay(m: ShippedMetricInput, deltaAs: TileSpec['deltaAs']): string {
  if (m.delta_display) return m.delta_display
  const delta = shippedDelta(m)
  if (delta === null) return '—'
  if (deltaAs === 'points') return signed(delta, ' pts')
  if (deltaAs === 'absolute') return signed(delta, '')
  if (finite(m.previous_total) && m.previous_total > 0) return signed((delta / m.previous_total) * 100, '%')
  return signed(delta, '')
}

export function shippedTotalDisplay(total: number, unit: TileSpec['unit']): string {
  return unit === 'percent' ? `${Math.round(total)}%` : formatInteger(total)
}

/** The five tiles, in board order. A null tile, or one with no total, is unavailable (never a fake 0). */
export function shippedTiles(input: ShippedInput): ShippedTile[] {
  const days = input.window.days
  return SHIPPED_TILE_KEYS.map((key): ShippedTile => {
    const spec = SHIPPED_TILES[key]
    const m = input[key]
    if (!m || !finite(m.total)) return { key, label: spec.label, available: false, reason: m?.reason ?? input.reasons?.[key] ?? null }
    const total = shippedTotalDisplay(m.total, spec.unit)
    const delta = shippedDeltaDisplay(m, spec.deltaAs)
    return {
      key,
      label: spec.label,
      available: true,
      total,
      delta,
      tone: shippedTone(shippedDelta(m), spec.goodWhen),
      bars: shippedBars(normaliseSeries(m.series, input.window.to, days)),
      summary: `${spec.label}: ${total}, ${delta} vs the ${days} days before`,
    }
  })
}

/** Header line: "Last 14 days, vs the 14 before". */
export function shippedWindowLine(days: number): string {
  return `Last ${days} days, vs the ${days} before`
}

/** Sparkline rects in a `viewBox="0 0 width height"` box: one slot per bar, a 2-unit gap. */
export function shippedBarRects(bars: readonly ShippedBar[], height = 26, slot = 10, gap = 2): { x: number; y: number; width: number; height: number }[] {
  return bars.map((b, i) => {
    const h = (b.height / 100) * height
    return { x: i * slot, y: height - h, width: slot - gap, height: h }
  })
}

/** Every tile unavailable, for a server that has no /metrics/shipped at all (404). */
export function shippedUnavailableTiles(reason: string | null = null): ShippedTileUnavailable[] {
  return SHIPPED_TILE_KEYS.map((key) => ({ key, label: SHIPPED_TILES[key].label, available: false, reason }))
}
