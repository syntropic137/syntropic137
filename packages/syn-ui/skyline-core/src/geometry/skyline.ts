/**
 * Skyline chart layout (Main and PhoneOverview boards): every day of a range
 * as an extruded bar on a week grid, taller for more sessions.
 *
 * The grid starts on the Sunday on or before the range start. Week w is a
 * column; the weekday picks a depth row j = 6 - dow, so Sunday sits at the
 * back and Saturday in front. Each row is shifted right by `rowDx` and up by
 * `rowDy`, which gives the receding oblique floor. Rows are painted back to
 * front (j = 6 first), side, then front, then top, so nothing needs sorting.
 *
 * Dates are plain ISO day keys ("2026-08-28") and all arithmetic is UTC, so
 * the layout is identical in every time zone and in Node.
 */
import { type FacePaths, obliqueBox, obliqueFloor } from './extrude'
import { round2 } from './path'
import { sqrtHeight } from './scale'

/** Token counts by bucket, as the Usage Meter and Day Readout show them. */
export interface SkylineTokens {
  input: number
  output: number
  cacheWrite: number
  cacheRead: number
}

/** One day of activity. Days with no sessions may be omitted. */
export interface SkylineDay {
  /** ISO day key, "2026-08-28". */
  date: string
  sessions: number
  executions?: number
  commits?: number
  /** Spend in USD; null when unknown. */
  costUsd?: number | null
  tokens?: SkylineTokens | null
}

/** Inclusive ISO day range. */
export interface SkylineRange {
  start: string
  end: string
}

/** Drawing constants. Two presets reproduce the canvas boards. */
export interface SkylineDims {
  /** Column pitch per week. */
  week: number
  /** Bar width (front face). */
  bar: number
  /** Per-row shift right and up (the floor recedes). */
  rowDx: number
  rowDy: number
  /** Extrusion depth of each bar. */
  depthX: number
  depthY: number
  /** x of the first week's back row... front row, j = 0. */
  originX: number
  /** Ground line of the front row. */
  groundY: number
  maxHeight: number
  /** Shortest bar for a day with at least one session. */
  minHeight: number
  /** Minimum hit target height, in viewBox units. */
  hitMin: number
  hitPad: number
  /** Baseline of the month labels. */
  labelY: number
  /** Where the leader line turns toward the readout (desktop only). */
  leadY: number
  viewBox: { x: number; y: number; width: number; height: number }
}

/** Desktop, a full year (Main board). */
export const SKYLINE_YEAR: SkylineDims = {
  week: 18,
  bar: 12,
  rowDx: 8,
  rowDy: 6.5,
  depthX: 5.6,
  depthY: 4.55,
  originX: 20,
  groundY: 160,
  maxHeight: 90,
  minHeight: 12,
  hitMin: 22,
  hitPad: 3,
  labelY: 182,
  leadY: -14,
  viewBox: { x: 0, y: -30, width: 1040, height: 220 },
}

/** Phone, the last 16 weeks (PhoneOverview board). */
export const SKYLINE_WEEKS: SkylineDims = {
  week: 19.3,
  bar: 13.5,
  rowDx: 6,
  rowDy: 5,
  depthX: 4.2,
  depthY: 3.5,
  originX: 6,
  groundY: 118,
  maxHeight: 72,
  minHeight: 11,
  hitMin: 30,
  hitPad: 3,
  labelY: 140,
  leadY: 0,
  viewBox: { x: 0, y: 0, width: 350, height: 146 },
}

export const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'] as const
export const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'] as const

const DAY_MS = 86_400_000

/** "2026-08-28" -> UTC epoch ms at midnight; NaN when malformed. */
export function dayMs(key: string): number {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(key)
  if (!m) return Number.NaN
  return Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
}

/** UTC epoch ms -> "2026-08-28". */
export function dayFromMs(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10)
}

/** Shift a day key by whole days. */
export function addDays(key: string, days: number): string {
  return dayFromMs(dayMs(key) + days * DAY_MS)
}

/** 0 = Sunday. */
export function weekday(key: string): number {
  return new Date(dayMs(key)).getUTCDay()
}

/** The Sunday on or before the day. */
export function weekStart(key: string): string {
  return addDays(key, -weekday(key))
}

/** Every day of a calendar year. */
export function yearRange(year: number): SkylineRange {
  return { start: `${year}-01-01`, end: `${year}-12-31` }
}

/** Whole weeks ending with the week that holds `today` (Sunday to Saturday). */
export function recentWeeksRange(today: string, weeks = 16): SkylineRange {
  const lastSunday = weekStart(today)
  return { start: addDays(lastSunday, -7 * (weeks - 1)), end: addDays(lastSunday, 6) }
}

/** "Fri, Aug 28" (weekday, month, day). */
export function dayLabel(key: string): string {
  const d = new Date(dayMs(key))
  return `${WEEKDAYS[d.getUTCDay()]}, ${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`
}

export interface SkylineBar {
  date: string
  day: SkylineDay
  /** Position among the active days of the layout (stepper order). */
  index: number
  /** Depth row, 0 = front (Saturday). */
  row: number
  /** Left edge and ground of the front face. */
  x: number
  y: number
  height: number
  paths: FacePaths
  /** Where the leader line starts: the middle of the top face. */
  anchor: { x: number; y: number }
  /** Pointer target in viewBox units; front rows stack above back rows. */
  hit: { x: number; y: number; width: number; height: number; z: number }
  /** "Fri, Aug 28: 43 sessions". */
  label: string
}

export interface SkylineLayout {
  dims: SkylineDims
  /** "0 -30 1040 220". */
  viewBox: string
  /** Floor tiles of past days without sessions, one path. */
  floor: string
  /** Floor tiles after `today`, one path. */
  future: string
  /** Faces per depth row, index = row (0 front). Paint from row 6 down to 0. */
  rows: FacePaths[]
  /** Active days, oldest first. */
  bars: SkylineBar[]
  months: { x: number; y: number; label: string }[]
  maxSessions: number
}

export interface SkylineLayoutInput {
  days: readonly SkylineDay[]
  range: SkylineRange
  /** Days after this one are drawn as future tiles. */
  today: string
  dims?: SkylineDims
  /** Height scale; defaults to the busiest day in `days` (all of them, not just the range), so toggling the range keeps heights. */
  maxSessions?: number
}

function sessionWord(n: number): string {
  return n === 1 ? 'session' : 'sessions'
}

export function layoutSkyline(input: SkylineLayoutInput): SkylineLayout {
  const dims = input.dims ?? SKYLINE_YEAR
  const { byDate, maxSeen } = activeDays(input.days)
  const maxSessions = input.maxSessions ?? maxSeen

  const start = dayMs(input.range.start)
  const end = dayMs(input.range.end)
  const grid = dayMs(weekStart(input.range.start))
  const acc: SkylineAccumulator = {
    rows: Array.from({ length: 7 }, () => ({ front: [], side: [], top: [] })),
    floor: [],
    future: [],
    bars: [],
    months: [],
  }

  if (Number.isFinite(start) && Number.isFinite(end) && end >= start) {
    const ctx: SkylinePlacement = { dims, byDate, maxSessions, today: dayMs(input.today) }
    const span = Math.round((end - grid) / DAY_MS)
    for (let idx = 0; idx <= span; idx++) {
      const t = grid + idx * DAY_MS
      if (t >= start) placeSkylineDay(acc, ctx, idx, t)
    }
  }

  const vb = dims.viewBox
  return {
    dims,
    viewBox: `${vb.x} ${vb.y} ${vb.width} ${vb.height}`,
    floor: acc.floor.join(''),
    future: acc.future.join(''),
    rows: acc.rows.map((r) => ({ front: r.front.join(''), side: r.side.join(''), top: r.top.join('') })),
    bars: acc.bars,
    months: acc.months,
    maxSessions,
  }
}

interface SkylineAccumulator {
  rows: { front: string[]; side: string[]; top: string[] }[]
  floor: string[]
  future: string[]
  bars: SkylineBar[]
  months: SkylineLayout['months']
}

interface SkylinePlacement {
  dims: SkylineDims
  byDate: Map<string, SkylineDay>
  maxSessions: number
  today: number
}

/** Days with sessions by date, and the busiest count among them. */
function activeDays(days: readonly SkylineDay[]): { byDate: Map<string, SkylineDay>; maxSeen: number } {
  const byDate = new Map<string, SkylineDay>()
  let maxSeen = 0
  for (const d of days) {
    if (d.sessions <= 0) continue
    byDate.set(d.date.slice(0, 10), d)
    maxSeen = Math.max(maxSeen, d.sessions)
  }
  return { byDate, maxSeen }
}

/** One grid cell `idx` days after the grid's first Sunday: month tick, then a future tile, floor tile or bar. */
function placeSkylineDay(acc: SkylineAccumulator, ctx: SkylinePlacement, idx: number, t: number): void {
  const { week: A, bar: W, rowDx, rowDy, depthX: EX, depthY: EY, originX, groundY } = ctx.dims
  const w = Math.floor(idx / 7)
  const j = 6 - (idx % 7)
  const tile = { x: originX + w * A + j * rowDx, y: groundY - j * rowDy, width: W, dx: EX, dy: EY }
  const date = new Date(t)
  if (date.getUTCDate() === 1) acc.months.push({ x: round2(originX + w * A), y: ctx.dims.labelY, label: MONTHS[date.getUTCMonth()] ?? '' })
  const key = dayFromMs(t)
  const day = ctx.byDate.get(key)
  if (t > ctx.today) acc.future.push(obliqueFloor(tile))
  else if (!day) acc.floor.push(obliqueFloor(tile))
  else addSkylineBar(acc, ctx, { key, day, row: j, tile })
}

function addSkylineBar(acc: SkylineAccumulator, ctx: SkylinePlacement, at: { key: string; day: SkylineDay; row: number; tile: { x: number; y: number; width: number; dx: number; dy: number } }): void {
  const { dims } = ctx
  const { key, day, row: j, tile } = at
  const { x: X, y: Y, width: W, dx: EX, dy: EY } = tile
  const h = sqrtHeight(day.sessions, ctx.maxSessions, dims.maxHeight, dims.minHeight)
  const paths = obliqueBox({ ...tile, height: h })
  acc.rows[j]!.front.push(paths.front)
  acc.rows[j]!.side.push(paths.side)
  acc.rows[j]!.top.push(paths.top)
  const pad = dims.hitPad
  const y1 = Y + pad
  let y0 = Y - h - EY - pad
  if (y1 - y0 < dims.hitMin) y0 = y1 - dims.hitMin
  acc.bars.push({
    date: key,
    day,
    index: acc.bars.length,
    row: j,
    x: X,
    y: Y,
    height: h,
    paths,
    anchor: { x: round2(X + (W + EX) / 2), y: round2(Y - h - EY / 2) },
    hit: { x: round2(X - pad), y: round2(y0), width: round2(W + EX + pad * 2), height: round2(y1 - y0), z: 10 - j },
    label: `${dayLabel(key)}: ${day.sessions} ${sessionWord(day.sessions)}`,
  })
}

/**
 * Leader line from a bar's top face up to `dims.leadY`, then across to
 * `targetX` (the readout dock's left edge, in viewBox units).
 */
export function skylineLeadPath(bar: Pick<SkylineBar, 'anchor'>, targetX: number, dims: SkylineDims = SKYLINE_YEAR): string {
  return `M${bar.anchor.x},${bar.anchor.y}V${dims.leadY}H${round2(targetX)}`
}

/** A viewBox-unit rectangle as CSS percentages of the chart box. */
export function hitStyle(hit: SkylineBar['hit'], dims: SkylineDims): { left: string; top: string; width: string; height: string } {
  const vb = dims.viewBox
  const pc = (v: number, of: number) => `${round2((v / of) * 100)}%`
  return {
    left: pc(hit.x - vb.x, vb.width),
    top: pc(hit.y - vb.y, vb.height),
    width: pc(hit.width, vb.width),
    height: pc(hit.height, vb.height),
  }
}

/** Short description for the chart's accessible name. */
export function describeSkyline(layout: SkylineLayout, rangeLabel: string): string {
  const n = layout.bars.length
  if (n === 0) return `Activity skyline for ${rangeLabel}. No sessions yet.`
  const first = layout.bars[0]!
  const last = layout.bars[n - 1]!
  const top = layout.bars.reduce((a, b) => (b.day.sessions > a.day.sessions ? b : a))
  const [, fm, fd] = /^\d{4}-(\d{2})-(\d{2})/.exec(first.date) ?? []
  const [, lm, ld] = /^\d{4}-(\d{2})-(\d{2})/.exec(last.date) ?? []
  const md = (m?: string, d?: string) => `${MONTHS[Number(m) - 1] ?? ''} ${Number(d)}`
  const [, tm, td] = /^\d{4}-(\d{2})-(\d{2})/.exec(top.date) ?? []
  const span = n === 1 ? `One active day, ${md(fm, fd)}` : `${n} active days run from ${md(fm, fd)} to ${md(lm, ld)}`
  return `Activity skyline for ${rangeLabel}. ${span}, and ${md(tm, td)} is the tallest with ${top.day.sessions} ${sessionWord(top.day.sessions)}.`
}
