/**
 * The run city (Landing hero): one isometric block per day of agent runs on
 * a `cols` x `rows` ground grid, taller for busier days. Ported from city()
 * in design/reference/gen_landing2.py; every block is the brand cube
 * (isoCube, 2:1 pixel isometric).
 *
 * Driven by the Overview skyline's per-day series (SkylineDay): day k sits
 * at column k % cols, row floor(k / cols), so the oldest day is at the back
 * left. Activity is sessions over the busiest day, height
 * 3 + activity * cell * 2.6, opacity 0.28 + 0.72 * min(1, activity * 1.3).
 * Blocks come back in draw order (back to front, by diagonal then column),
 * with `wave` (the diagonal) for a staggered entrance.
 */
import { type IsoCube, isoCube } from './isoCube'
import { addDays, type SkylineDay } from './skyline'

/** run: a normal day; live: running now (pulses); failed: only failed runs; errored: mixed or scorer errors (amber). */
export type CityTone = 'run' | 'live' | 'failed' | 'errored'

/** Base colour per tone, as token expressions (extrudeColors() lights and shades the faces). */
export const CITY_TONE_FILL: Record<CityTone, string> = {
  run: 'var(--ds-color-accent)',
  live: 'var(--ds-color-accent)',
  failed: 'var(--sky-status-failed)',
  errored: 'var(--sky-status-interrupted)',
}

export interface IsoCityOptions {
  cols: number
  rows: number
  /** Width of one ground cell, in viewBox units. */
  cell: number
  /** Block indexes (k) to mark live, failed or errored; these win over the day's outcomes. */
  live?: Iterable<number>
  failed?: Iterable<number>
  errored?: Iterable<number>
  /** Sessions that count as full activity (default: the busiest day shown). */
  maxSessions?: number
}

export interface CityBlock extends IsoCube<CityTone> {
  tone: CityTone
  /** Grid index, row * cols + column. */
  index: number
  column: number
  row: number
  /** The day this block shows; null when the series is shorter than the grid. */
  date: string | null
  /** Ground diamond centre. */
  x: number
  y: number
  height: number
  /** 0..1 share of the busiest day. */
  activity: number
  opacity: number
  /** Diagonal (column + row): blocks of one wave rise together, back first. */
  wave: number
}

export interface IsoCityLayout {
  blocks: CityBlock[]
  width: number
  height: number
  viewBox: string
  /** Outline of the ground grid, as polygon points. */
  floor: string
  /** The soft accent glow under the city. */
  glow: { cx: number; cy: number; rx: number; ry: number }
}

const r1 = (v: number) => Math.round(v * 10) / 10

function dayTone(k: number, day: SkylineDay | undefined, sets: { live: Set<number>; failed: Set<number>; errored: Set<number> }): CityTone {
  if (sets.failed.has(k)) return 'failed'
  if (sets.errored.has(k)) return 'errored'
  if (sets.live.has(k)) return 'live'
  const o = day?.outcomes
  if (o && o.failed > 0) return o.passed > 0 ? 'errored' : 'failed'
  return 'run'
}

interface Cell {
  k: number
  i: number
  j: number
  day: SkylineDay | undefined
  act: number
  h: number
}

function cells(days: readonly SkylineDay[], o: IsoCityOptions): Cell[] {
  const n = o.cols * o.rows
  const shown = days.slice(-n)
  const max = o.maxSessions ?? shown.reduce((m, d) => Math.max(m, d.sessions), 0)
  const out: Cell[] = []
  for (let j = 0; j < o.rows; j++) {
    for (let i = 0; i < o.cols; i++) {
      const k = j * o.cols + i
      const day = shown[k]
      const act = day && max > 0 ? Math.max(0, day.sessions) / max : 0
      out.push({ k, i, j, day, act, h: 3 + act * o.cell * 2.6 })
    }
  }
  return out
}

/** Lay out the city for `days` (oldest first; the last cols * rows are shown). */
export function isoCity(days: readonly SkylineDay[], options: IsoCityOptions): IsoCityLayout {
  const { cols, rows, cell } = options
  const hw = cell / 2
  const hh = cell / 4
  const sets = { live: new Set(options.live ?? []), failed: new Set(options.failed ?? []), errored: new Set(options.errored ?? []) }
  const grid = cells(days, options)
  const ox = rows * hw + 30
  const oy = grid.reduce((m, c) => Math.max(m, c.h), 0) + 30
  const width = (cols + rows) * hw + 60
  const height = oy + (cols + rows) * hh + 20
  const gap = cell * 0.09
  const blocks = [...grid]
    .sort((a, b) => a.i + a.j - (b.i + b.j) || a.i - b.i)
    .map((c): CityBlock => {
      const x = ox + (c.i - c.j) * hw
      const y = oy + (c.i + c.j) * hh
      const tone = dayTone(c.k, c.day, sets)
      const faces = isoCube({ x, y, size: hw - gap, height: c.h, tone })
      return {
        ...faces,
        tone,
        index: c.k,
        column: c.i,
        row: c.j,
        date: c.day?.date ?? null,
        x,
        y,
        height: c.h,
        activity: c.act,
        opacity: Math.round((0.28 + 0.72 * Math.min(1, c.act * 1.3)) * 100) / 100,
        wave: c.i + c.j,
      }
    })
  const floor = [
    [ox, oy - hh],
    [ox + cols * hw, oy + cols * hh - hh],
    [ox + (cols - rows) * hw, oy + (cols + rows) * hh - hh],
    [ox - rows * hw, oy + rows * hh - hh],
  ]
    .map(([x, y]) => `${r1(x ?? 0)},${r1(y ?? 0)}`)
    .join(' ')
  const w = Math.round(width)
  const h = Math.round(height)
  return {
    blocks,
    width: w,
    height: h,
    viewBox: `0 0 ${w} ${h}`,
    floor,
    glow: { cx: Math.round(width * 0.55), cy: Math.round(height * 0.62), rx: Math.round(width * 0.5), ry: Math.round(height * 0.42) },
  }
}

/**
 * Sample activity of the landing hero (sample data, not real runs): a ramp
 * toward the front right with a deterministic wobble and a few quiet days,
 * exactly as the board draws it. Values are 0..1 per block index.
 */
export function cityActivitySample(cols: number, rows: number): number[] {
  const out: number[] = []
  for (let j = 0; j < rows; j++) {
    for (let i = 0; i < cols; i++) {
      const k = j * cols + i
      const ramp = (i + (rows - j) * 0.35) / (cols + rows * 0.35)
      const wob = ((k * 37) % 13) / 13
      let act = (0.12 + 0.88 * ramp) * (0.4 + 0.6 * wob)
      if ((k * 17) % 9 === 0) act *= 0.2
      out.push(act)
    }
  }
  return out
}

/** SAMPLE_SESSIONS sessions is full activity in sampleCityDays(); pass it as `maxSessions`. */
export const SAMPLE_SESSIONS = 1000

/** cityActivitySample() as SkylineDay[] ending on `end` (sample data for the hero and the social image). */
export function sampleCityDays(cols: number, rows: number, end: string): SkylineDay[] {
  const acts = cityActivitySample(cols, rows)
  return acts.map((a, k) => ({
    date: addDays(end, k - (acts.length - 1)),
    sessions: Math.round(a * SAMPLE_SESSIONS),
  }))
}

/** Entrance stagger of a city block (seconds), by its diagonal: 0.15s plus 0.035s per wave, as on the board. */
export function cityDelay(wave: number): number {
  return Math.round((0.15 + wave * 0.035) * 100) / 100
}

/** Board pulse and flash start this long after a block's rise begins (seconds). */
export const CITY_SIGNAL_DELAY = 1.6
