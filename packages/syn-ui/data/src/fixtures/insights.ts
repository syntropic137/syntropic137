/**
 * Overview Skyline data: one bucket per day with the full breakdown. The
 * first rows are the Overview board's DAYS sample; the rest is generated so
 * a full year renders.
 */
import type { ContributionHeatmap, HeatmapDay } from '../resources/insights'
import { type FixtureRoute, route } from './define'
import { DAY, FIXTURE_NOW } from './seed'

// [date, sessions, executions, commits, cost_usd, input, output, cache_write, cache_read]
type Row = [string, number, number, number, number, number, number, number, number]
const BOARD_DAYS: Row[] = [
  ['2026-07-25', 8, 6, 0, 0.2769, 73903, 8458, 60299, 828266],
  ['2026-07-28', 4, 3, 0, 0.1737, 41859, 7150, 30391, 568180],
  ['2026-08-06', 1, 1, 0, 0, 0, 0, 0, 0],
  ['2026-08-08', 5, 4, 0, 0.043, 17, 279, 29892, 29688],
  ['2026-08-10', 5, 5, 0, 0.1793, 78954, 7729, 0, 617216],
  ['2026-08-17', 3, 2, 0, 0.1258, 29972, 4808, 30385, 326031],
  ['2026-08-21', 10, 6, 0, 0.1324, 62, 4626, 69736, 139626],
  ['2026-08-22', 5, 2, 0, 0.2159, 950, 5038, 70631, 204525],
  ['2026-08-26', 5, 2, 0, 0.1266, 50, 5760, 66436, 82410],
  ['2026-08-27', 19, 11, 0, 0.661, 37111, 21117, 154563, 953286],
  ['2026-08-28', 43, 23, 0, 4.9849, 464027, 137651, 517201, 4556030],
]

function day(r: Row): HeatmapDay {
  const [date, sessions, executions, commits, cost, input, output, cacheWrite, cacheRead] = r
  return {
    date,
    count: sessions,
    breakdown: {
      sessions,
      executions,
      commits,
      cost_usd: cost,
      tokens: input + output + cacheWrite + cacheRead,
      input_tokens: input,
      output_tokens: output,
      cache_creation_tokens: cacheWrite,
      cache_read_tokens: cacheRead,
    },
  }
}

/** Board days plus a sparse, deterministic tail from September to FIXTURE_NOW. */
function days(): HeatmapDay[] {
  const out = BOARD_DAYS.map(day)
  for (let t = Date.UTC(2026, 8, 1); t <= FIXTURE_NOW; t += DAY) {
    const n = new Date(t).getUTCDate()
    if (n % 3 === 0) continue
    const sessions = ((n * 7) % 13) + 1
    out.push(day([new Date(t).toISOString().slice(0, 10), sessions, Math.ceil(sessions / 2), n % 4, sessions * 0.031, sessions * 1200, sessions * 900, sessions * 4100, sessions * 38_000]))
  }
  return out
}

export const insightRoutes: FixtureRoute[] = [
  route('GET', '/insights/contribution-heatmap', ({ query }): ContributionHeatmap => {
    const all = days()
    const start = query.get('start_date') ?? '2025-10-08'
    const end = query.get('end_date') ?? new Date(FIXTURE_NOW).toISOString().slice(0, 10)
    const inRange = all.filter((d) => d.date >= start && d.date <= end)
    return { metric: query.get('metric') ?? 'sessions', start_date: start, end_date: end, total: inRange.reduce((n, d) => n + d.count, 0), days: inRange }
  }),
]
