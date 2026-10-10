/**
 * The Overview IsoCity (Main and PhoneOverview boards, plan 4a and 4d): an
 * isometric floor of days. Weeks come toward the viewer (right and down),
 * and so do the days of a week: Monday at the back, Sunday in front (the
 * owner's Oct 10 request), so today is never hidden behind a taller,
 * later day. The boards predate it and draw Monday in front; pass
 * `weekdayAxis: 'monday-front'` to reproduce them. A day with
 * sessions is a block, sqrt-scaled to the busiest day; an empty day is a
 * floor tile and a future day a dashed outline.
 *
 * Projection, from the board script: column c (week), depth r and height
 * z map to (ox + c*ax + r*bx, oy + c*ay + r*by - z). Depth 0 is the front
 * row; a weekday's depth is 6 - weekday (Monday back) by default. A block covers
 * f of its cell in both directions, so a week step (ax) is wider than a
 * block's footprint (f * (ax + bx)) and blocks in one row never overlap.
 * Rows come back far to near (Monday first) and each row left to right,
 * which is the painter's order.
 *
 * Tone tiers: `fail` when failed runs are known, at least one, and at
 * least half the day's executions; else `hot` from 30% of the busiest day,
 * `mid` from 10%, `dim` below. Days without a failed count are never `fail`.
 *
 * `pad` extra weeks are laid out on each side of the window (edge blocks),
 * so a glide or a drag has something to bring into view. Columns are
 * relative to the window's first week: -pad .. window - 1 + pad.
 */
import { round2, type Point } from './path'
import { MONTHS, WEEKDAYS, addDays, dayMs, type SkylineDay } from './skyline'

/** Geometry constants: the `G` object of each board script. */
export interface IsoCityDims {
  /** Weeks in the window. */
  win: number
  /** Screen step of one week (toward the viewer). */
  ax: number
  ay: number
  /** Screen step of one weekday (receding). */
  bx: number
  by: number
  /** Share of a cell a block covers. */
  f: number
  /** Ground point of the window's first Monday. */
  ox: number
  oy: number
  /** Tallest block and the shortest block of an active day. */
  hmax: number
  hmin: number
  /** View box. */
  vw: number
  vh: number
  /** Where the leader line to the docked readout turns (0: no leader, phone). */
  leadY: number
  leadX: number
  labelDy: number
  /** Minimum hit box height. */
  hitmin: number
  /** Height of today's beam. */
  beam: number
  /** Week strip: a tick every n months. */
  tickEvery: number
}

/** Main board. */
export const ISO_CITY_DESKTOP: IsoCityDims = { win: 14, ax: 52, ay: 7, bx: 17, by: -11, f: 0.74, ox: 20, oy: 196, hmax: 110, hmin: 6, vw: 1040, vh: 330, leadY: 14, leadX: 846, labelDy: 22, hitmin: 22, beam: 72, tickEvery: 1 }

/** PhoneOverview board. */
export const ISO_CITY_PHONE: IsoCityDims = { win: 8, ax: 34, ay: 5, bx: 10, by: -7, f: 0.72, ox: 10, oy: 118, hmax: 64, hmin: 4, vw: 350, vh: 186, leadY: 0, leadX: 0, labelDy: 18, hitmin: 30, beam: 40, tickEvery: 3 }

export type IsoTone = 'dim' | 'mid' | 'hot' | 'fail'
export const ISO_TONES: readonly IsoTone[] = ['dim', 'mid', 'hot', 'fail']

/** Which weekday sits at the back: Monday (default, days come forward) or Sunday (the boards). */
export type IsoWeekdayAxis = 'monday-back' | 'monday-front'

/** Depth of weekday `r` (0 = front row). */
export function isoDepth(r: number, axis: IsoWeekdayAxis = 'monday-back'): number {
  return axis === 'monday-back' ? 6 - r : r
}

/** True when failed executions are known, at least one, and at least half the executions: the coral rule for a day and a week alike. */
export function isFailing(failed: number | null | undefined, executions: number | null | undefined): boolean {
  const f = failed ?? 0
  return f > 0 && f * 2 >= (executions ?? 0)
}

/** One week of the history, Monday first; `days[i]` is null for a day with no data. */
export interface IsoCityWeek {
  /** Monday, "2026-08-24". */
  start: string
  days: (SkylineDay | null)[]
}

/** Weekday names, Monday first (index = weekday row; its depth comes from the weekday axis). */
export const ISO_WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const

/** Group days into `count` whole weeks starting on the Monday `start`. */
export function isoCityWeeks(days: readonly SkylineDay[], start: string, count: number): IsoCityWeek[] {
  const byDate = new Map(days.map((d) => [d.date, d]))
  return Array.from({ length: Math.max(0, count) }, (_, w) => {
    const monday = addDays(start, 7 * w)
    return { start: monday, days: Array.from({ length: 7 }, (_, r) => byDate.get(addDays(monday, r)) ?? null) }
  })
}

/** The tone tier of a day with sessions. */
export function isoTone(day: SkylineDay, maxSessions: number): IsoTone {
  if (isFailing(day.failed, day.executions)) return 'fail'
  const ratio = maxSessions > 0 ? day.sessions / maxSessions : 0
  if (ratio >= 0.3) return 'hot'
  return ratio >= 0.1 ? 'mid' : 'dim'
}

/** Block height: sqrt of the share of the busiest day, never below `hmin`. */
export function isoHeight(sessions: number, maxSessions: number, dims: IsoCityDims): number {
  if (maxSessions <= 0) return dims.hmin
  return Math.max(dims.hmin, Math.round(dims.hmax * Math.sqrt(Math.max(0, sessions) / maxSessions)))
}

/** "Mon, Aug 3: 5 sessions, 2 failed". */
export function isoDayLabel(day: SkylineDay): string {
  const d = new Date(dayMs(day.date))
  const wd = WEEKDAYS[d.getUTCDay()]
  const s = `${day.sessions} ${day.sessions === 1 ? 'session' : 'sessions'}`
  const failed = day.failed ? `, ${day.failed} failed` : ''
  return `${wd}, ${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}: ${s}${failed}`
}

export interface IsoHitBox {
  x: number
  y: number
  width: number
  height: number
}

export interface IsoCityBlock {
  day: SkylineDay
  date: string
  /** Week index in the history. */
  week: number
  /** Column relative to the window's first week. */
  column: number
  /** Weekday, 0 = Monday .. 6 = Sunday. */
  row: number
  /** Depth on screen, 0 = front row (isoDepth). */
  depth: number
  tone: IsoTone
  height: number
  side: string
  front: string
  top: string
  /** Bounding box in view box units (focus ring); stacking order `z` (nearer and newer on top). */
  hit: IsoHitBox
  z: number
  /** The painted faces as polygons (side, front, top), for visible-surface picking. */
  faces: readonly (readonly Point[])[]
  /** Top centre, where the leader line starts. */
  anchor: Point
  label: string
  /** False for the `pad` weeks either side of the window. */
  inWindow: boolean
}

export interface IsoCityRow {
  row: number
  weekday: (typeof ISO_WEEKDAYS)[number]
  /** Left to right. */
  blocks: IsoCityBlock[]
}

export interface IsoCityLabel {
  /** SVG transform that lays the text on the floor at the iso angle. */
  transform: string
  text: string
  key: string
  inWindow: boolean
}

export interface IsoCityFloorLayout {
  dims: IsoCityDims
  viewBox: string
  /** Rows far to near (Monday first by default): draw in this order. */
  rows: IsoCityRow[]
  /** Every block in draw order. */
  blocks: IsoCityBlock[]
  /** Empty day tiles, in and outside the window. */
  floor: string
  floorEdge: string
  /** Future day outlines. */
  future: string
  futureEdge: string
  /** Days before `loadedFrom`: not loaded yet, so unknown rather than empty. */
  unloaded: string
  /** Today's tile and beam (null when today is not rendered). */
  today: { tile: string; beam: IsoHitBox } | null
  /** Tops of hot and failed blocks in the window, for the bloom. */
  glowHot: string
  glowFail: string
  months: IsoCityLabel[]
  /** Mon, Wed and Fri, painted past the window's newest week. */
  weekdays: IsoCityLabel[]
  /** The selected block (in the window) and its leader line to the dock. */
  selected: IsoCityBlock | null
  lead: string | null
  /** Translation of one week, for glides and drags. */
  weekStep: Point
}

export interface IsoCityFloorInput {
  weeks: readonly IsoCityWeek[]
  /** Week index of the window's first (oldest) week. */
  first: number
  today: string
  dims?: IsoCityDims
  /** Weeks shown (default dims.win). */
  window?: number
  pad?: number
  selected?: string | null
  /** Busiest day for the height and tone scale (default: the busiest in `weeks`). */
  maxSessions?: number
  /** Default 'monday-back'. */
  weekdayAxis?: IsoWeekdayAxis
  /** First day whose data is loaded; earlier days paint as unloaded, not empty. Default: everything is loaded. */
  loadedFrom?: string | null
}

interface Ctx {
  dims: IsoCityDims
  window: number
  first: number
  today: string
  max: number
  selected: string | null
  axis: IsoWeekdayAxis
  loadedFrom: string | null
}

const n2 = round2
const pt = (d: IsoCityDims, c: number, r: number, z: number): Point => [d.ox + c * d.ax + r * d.bx, d.oy + c * d.ay + r * d.by - z]
const path = (pts: readonly Point[]) => 'M' + pts.map(([x, y]) => `${n2(x)},${n2(y)}`).join('L') + 'Z'

/** Unit vectors along a week (u) and up a weekday row (v): the label matrix. */
function axes(d: IsoCityDims): { u: Point; v: Point } {
  const ul = Math.hypot(d.ax, d.ay)
  const vl = Math.hypot(d.bx, d.by)
  return { u: [d.ax / ul, d.ay / ul], v: [-d.bx / vl, -d.by / vl] }
}

function floorMatrix(d: IsoCityDims, at: Point): string {
  const { u, v } = axes(d)
  return `matrix(${[u[0], u[1], v[0], v[1], at[0], at[1]].map(n2).join(' ')})`
}

function tile(d: IsoCityDims, c: number, r: number): string {
  const F = d.f
  return path([pt(d, c, r, 0), pt(d, c + F, r, 0), pt(d, c + F, r + F, 0), pt(d, c, r + F, 0)])
}

function hitBox(d: IsoCityDims, c: number, r: number, h: number): IsoHitBox {
  const F = d.f
  const x0 = pt(d, c, r, 0)[0] - 2
  const x1 = pt(d, c + F, r + F, 0)[0] + 2
  const y1 = pt(d, c + F, r, 0)[1] + 3
  const y0 = Math.min(pt(d, c, r + F, h)[1] - 3, y1 - d.hitmin)
  return { x: n2(x0), y: n2(y0), width: n2(x1 - x0), height: n2(y1 - y0) }
}

const rounded = (pts: readonly Point[]): Point[] => pts.map(([x, y]) => [n2(x), n2(y)])

function block(ctx: Ctx, day: SkylineDay, week: number, c: number, wd: number): IsoCityBlock {
  const d = ctx.dims
  const F = d.f
  const r = isoDepth(wd, ctx.axis)
  const h = isoHeight(day.sessions, ctx.max, d)
  const top = pt(d, c + F / 2, r + F / 2, h)
  const sideQ = rounded([pt(d, c + F, r, 0), pt(d, c + F, r + F, 0), pt(d, c + F, r + F, h), pt(d, c + F, r, h)])
  const frontQ = rounded([pt(d, c, r, 0), pt(d, c + F, r, 0), pt(d, c + F, r, h), pt(d, c, r, h)])
  const topQ = rounded([pt(d, c, r, h), pt(d, c + F, r, h), pt(d, c + F, r + F, h), pt(d, c, r + F, h)])
  return {
    day,
    date: day.date,
    week,
    column: c,
    row: wd,
    depth: r,
    tone: isoTone(day, ctx.max),
    height: h,
    front: path(frontQ),
    side: path(sideQ),
    top: path(topQ),
    hit: hitBox(d, c, r, h),
    z: 10 + (6 - r) + c,
    faces: [sideQ, frontQ, topQ],
    anchor: [n2(top[0]), n2(top[1])],
    label: isoDayLabel(day),
    inWindow: c >= 0 && c < ctx.window,
  }
}

function busiest(weeks: readonly IsoCityWeek[]): number {
  let max = 0
  for (const w of weeks) for (const d of w.days) if (d && d.sessions > max) max = d.sessions
  return max
}

interface Paint {
  floor: string[]
  floorEdge: string[]
  future: string[]
  futureEdge: string[]
  unloaded: string[]
  rows: IsoCityBlock[][]
  today: { tile: string; beam: IsoHitBox } | null
}

function todayMark(d: IsoCityDims, c: number, r: number): { tile: string; beam: IsoHitBox } {
  const b = pt(d, c + d.f / 2, r + d.f / 2, 0)
  return { tile: tile(d, c, r), beam: { x: n2(b[0] - 1.5), y: n2(b[1] - d.beam), width: 3, height: d.beam } }
}

function paintCell(ctx: Ctx, paint: Paint, week: IsoCityWeek, w: number, c: number, wd: number): void {
  const d = ctx.dims
  const r = isoDepth(wd, ctx.axis)
  const date = addDays(week.start, wd)
  const inWindow = c >= 0 && c < ctx.window
  if (date === ctx.today) paint.today = todayMark(d, c, r)
  const day = week.days[wd]
  if (date > ctx.today) (inWindow ? paint.future : paint.futureEdge).push(tile(d, c, r))
  else if (ctx.loadedFrom !== null && date < ctx.loadedFrom) paint.unloaded.push(tile(d, c, r))
  else if (!day || day.sessions <= 0) (inWindow ? paint.floor : paint.floorEdge).push(tile(d, c, r))
  else paint.rows[wd]!.push(block(ctx, day, w, c, wd))
}

function monthLabels(ctx: Ctx, weeks: readonly IsoCityWeek[], from: number, to: number): IsoCityLabel[] {
  const out: IsoCityLabel[] = []
  let last = -1
  for (let c = from; c <= to; c++) {
    const week = weeks[ctx.first + c]
    if (!week) continue
    const d = new Date(dayMs(week.start))
    const m = d.getUTCMonth()
    if (m !== last || c === 0) {
      const text = MONTHS[m] + (m === 0 ? ` ${d.getUTCFullYear()}` : '')
      out.push({ transform: floorMatrix(ctx.dims, pt(ctx.dims, c + 0.04, -0.6, 0)), text, key: `${week.start}`, inWindow: c >= 0 && c < ctx.window })
    }
    last = m
  }
  return out
}

function weekdayLabels(ctx: Ctx): IsoCityLabel[] {
  const d = ctx.dims
  return [0, 2, 4].map((wd) => ({
    transform: floorMatrix(d, pt(d, ctx.window - 1 + d.f + 0.3, isoDepth(wd, ctx.axis) + 0.12, 0)),
    text: ISO_WEEKDAYS[wd]!,
    key: ISO_WEEKDAYS[wd]!,
    inWindow: true,
  }))
}

function leadPath(d: IsoCityDims, b: IsoCityBlock | null): string | null {
  if (!b || d.leadY <= 0) return null
  return `M${b.anchor[0]},${b.anchor[1]}V${d.leadY}H${d.leadX}`
}

/** Lay out the window starting at week `first`, plus `pad` weeks either side. */
export function layoutIsoCityFloor(input: IsoCityFloorInput): IsoCityFloorLayout {
  const dims = input.dims ?? ISO_CITY_DESKTOP
  const pad = Math.max(0, Math.floor(input.pad ?? 1))
  const ctx: Ctx = { dims, window: input.window ?? dims.win, first: input.first, today: input.today, max: input.maxSessions ?? busiest(input.weeks), selected: input.selected ?? null, axis: input.weekdayAxis ?? 'monday-back', loadedFrom: input.loadedFrom ?? null }
  const paint: Paint = { floor: [], floorEdge: [], future: [], futureEdge: [], unloaded: [], rows: [[], [], [], [], [], [], []], today: null }
  for (let c = -pad; c < ctx.window + pad; c++) {
    const week = input.weeks[ctx.first + c]
    if (!week) continue
    for (let r = 0; r < 7; r++) paintCell(ctx, paint, week, ctx.first + c, c, r)
  }
  // Far to near: the weekday at depth 6 first.
  const order = [0, 1, 2, 3, 4, 5, 6].sort((a, b) => isoDepth(b, ctx.axis) - isoDepth(a, ctx.axis))
  const rows = order.map((r): IsoCityRow => ({ row: r, weekday: ISO_WEEKDAYS[r]!, blocks: paint.rows[r]! }))
  const blocks = rows.flatMap((r) => r.blocks)
  const shown = blocks.filter((b) => b.inWindow)
  const selected = shown.find((b) => b.date === ctx.selected) ?? null
  return {
    dims,
    viewBox: `0 0 ${dims.vw} ${dims.vh}`,
    rows,
    blocks,
    floor: paint.floor.join(''),
    floorEdge: paint.floorEdge.join(''),
    future: paint.future.join(''),
    futureEdge: paint.futureEdge.join(''),
    unloaded: paint.unloaded.join(''),
    today: paint.today,
    glowHot: shown.filter((b) => b.tone === 'hot').map((b) => b.top).join(''),
    glowFail: shown.filter((b) => b.tone === 'fail').map((b) => b.top).join(''),
    months: monthLabels(ctx, input.weeks, -pad, ctx.window - 1 + pad),
    weekdays: weekdayLabels(ctx),
    selected,
    lead: leadPath(dims, selected),
    weekStep: [dims.ax, dims.ay],
  }
}
