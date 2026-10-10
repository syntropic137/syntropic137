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
 * Camera tilt: the board numbers were drawn looking down at
 * SKYLINE_BOARD_ELEVATION degrees. `dims.elevation` raises the camera; the
 * floor rows open up by sin(e) / sin(30) and the bars shorten by
 * cos(e) / cos(30), so back rows peek out from behind the front ones.
 * `dims.rowSpread` then widens the gap between rows, so a short day behind a
 * tall one keeps part of its top in view (feedback 75cf7eb2).
 *
 * Pointer picking: each bar's hit shape is its silhouette (floor, front,
 * side and top faces), tested front row first, so the face you see is the
 * day you get (pickSkylineBar).
 *
 * Dates are plain ISO day keys ("2026-08-28") and all arithmetic is UTC, so
 * the layout is identical in every time zone and in Node.
 */
import { type FaceColors, type FacePaths, extrudeColors, obliqueBox, obliqueFloor } from './extrude'
import { type Point, polygonPath, round2 } from './path'
import { sqrtHeight } from './scale'
import { type SkylineOutcomes, type SkylineTone, SKYLINE_TONE_FILL, skylineTone } from './skylineTone'

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
  /** Failed runs that day; absent when the API does not send it (the IsoCity never paints such a day coral). */
  failed?: number | null
  tokens?: SkylineTokens | null
  /** Finished runs; when absent the top face uses the session-count ramp. */
  outcomes?: SkylineOutcomes | null
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
  /** Per-row shift right and up (the floor recedes), as drawn at SKYLINE_BOARD_ELEVATION. */
  rowDx: number
  rowDy: number
  /** Extrusion depth of each bar, at SKYLINE_BOARD_ELEVATION. */
  depthX: number
  depthY: number
  /** Camera angle above the ground plane, degrees (0 = side on, 90 = straight down). */
  elevation: number
  /** Skyline: multiplies the gap between depth rows (1 = the board's floor). */
  rowSpread: number
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

/** The camera angle the canvas boards were drawn at; dims at this elevation reproduce them exactly. */
export const SKYLINE_BOARD_ELEVATION = 30

/**
 * Default camera (owner tweaks after demo): more top-down than the boards,
 * with the rows spread apart, so every bar of the fixtures year and of a
 * pinned live year keeps a pickable part of its top face in view
 * (skylineView.test.ts checks it). 60 degrees with the board's floor hid
 * live days behind taller ones (feedback 75cf7eb2).
 */
export const SKYLINE_ELEVATION = 68

/** Default row spread: half as much floor again between depth rows. */
export const SKYLINE_ROW_SPREAD = 1.5

/** Desktop, a full year (Main board). */
export const SKYLINE_YEAR: SkylineDims = {
  week: 18,
  bar: 12,
  rowDx: 8,
  rowDy: 6.5,
  depthX: 5.6,
  depthY: 4.55,
  elevation: SKYLINE_ELEVATION,
  rowSpread: SKYLINE_ROW_SPREAD,
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
  elevation: SKYLINE_ELEVATION,
  rowSpread: SKYLINE_ROW_SPREAD,
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

const rad = (deg: number) => (Math.min(90, Math.max(0, deg)) * Math.PI) / 180

/** Dims as seen from `dims.elevation`: floor depth and bar heights rescaled from the board's camera. */
export function projectSkylineDims(dims: SkylineDims): SkylineDims {
  const board = rad(SKYLINE_BOARD_ELEVATION)
  const e = rad(dims.elevation)
  const floor = Math.sin(e) / Math.sin(board)
  const rise = Math.cos(e) / Math.cos(board)
  const rowDy = dims.rowDy * floor * dims.rowSpread
  const depthY = dims.depthY * floor
  const maxHeight = dims.maxHeight * rise
  // Keep the board's headroom above the tallest possible bar: move the top of the view with it.
  const shift = 6 * (dims.rowDy - rowDy) + (dims.maxHeight - maxHeight) + (dims.depthY - depthY)
  const vb = dims.viewBox
  return {
    ...dims,
    rowDy,
    depthY,
    maxHeight,
    minHeight: dims.minHeight * rise,
    leadY: dims.leadY + shift,
    viewBox: { ...vb, y: vb.y + shift, height: vb.height - shift },
  }
}

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
  /** Focus target in viewBox units (keyboard ring, dock overlap); front rows stack above back rows. */
  hit: { x: number; y: number; width: number; height: number; z: number }
  /** Silhouette (floor, front, side and top faces), the pointer hit shape. */
  outline: readonly Point[]
  /** Colour rule (skylineTone), its base colour and the extruded face colours. */
  tone: SkylineTone
  fill: string
  faces: FaceColors
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
  const drawn = projectSkylineDims(dims)
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
    const ctx: SkylinePlacement = { dims: drawn, byDate, maxSessions, today: dayMs(input.today) }
    const span = Math.round((end - grid) / DAY_MS)
    for (let idx = 0; idx <= span; idx++) {
      const t = grid + idx * DAY_MS
      if (t >= start) placeSkylineDay(acc, ctx, idx, t)
    }
  }

  const vb = drawn.viewBox
  return {
    dims: drawn,
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
  const tone = skylineTone(day, ctx.maxSessions)
  acc.bars.push({
    date: key,
    day,
    index: acc.bars.length,
    row: j,
    x: X,
    y: Y,
    height: h,
    paths,
    outline: boxOutline({ ...tile, height: h }),
    tone,
    fill: SKYLINE_TONE_FILL[tone],
    faces: extrudeColors(SKYLINE_TONE_FILL[tone]),
    anchor: { x: round2(X + (W + EX) / 2), y: round2(Y - h - EY / 2) },
    hit: { x: round2(X - pad), y: round2(y0), width: round2(W + EX + pad * 2), height: round2(y1 - y0), z: 10 - j },
    label: `${dayLabel(key)}: ${day.sessions} ${sessionWord(day.sessions)}`,
  })
}

/** The convex silhouette of an oblique box: ground front edge, side, back top edge, front top. */
function boxOutline(b: { x: number; y: number; width: number; height: number; dx: number; dy: number }): Point[] {
  const { x, y, width: w, height: h, dx, dy } = b
  return [[x, y], [x + w, y], [x + w + dx, y - dy], [x + w + dx, y - dy - h], [x + dx, y - dy - h], [x, y - h]]
}

/** True when (px, py) lies inside or on the convex polygon. */
export function inConvex(poly: readonly Point[], px: number, py: number): boolean {
  let sign = 0
  for (let i = 0; i < poly.length; i++) {
    const [ax, ay] = poly[i]!
    const [bx, by] = poly[(i + 1) % poly.length]!
    const cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
    if (cross === 0) continue
    const s = cross > 0 ? 1 : -1
    if (sign !== 0 && s !== sign) return false
    sign = s
  }
  return true
}

/**
 * The bar under a viewBox point, or null. Front rows are painted last, so
 * they are tested first: the frontmost visible face wins.
 */
export function pickSkylineBar(layout: Pick<SkylineLayout, 'bars'>, x: number, y: number): SkylineBar | null {
  let best: SkylineBar | null = null
  for (const b of layout.bars) {
    if ((best === null || b.row < best.row) && inConvex(b.outline, x, y)) best = b
  }
  return best
}

/** SVG path of a bar's hit silhouette. */
export function skylineOutlinePath(bar: Pick<SkylineBar, 'outline'>): string {
  return polygonPath(bar.outline)
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
