/**
 * Overview Skyline data: one bucket per day with the full breakdown. The
 * first rows are the Overview board's DAYS sample; the rest is generated so
 * a full year renders.
 */
import type { ContributionHeatmap, EventList, HeatmapDay, RecentEvent } from '../resources/insights'
import { RUNS } from './catalog'
import { type FixtureRoute, route } from './define'
import { DAY, FIXTURE_NOW, MINUTE, ago } from './seed'

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

/**
 * GET /events/recent?event_type=git_commit rows, in the two shapes the VPS
 * returns (2026-10-09): an agent commit (nested `data.git`, as written by the
 * workspace hook) and a GitHub push webhook commit (flat `commit_hash`).
 */
const COMMITS: Array<[string, string, string, string, number]> = [
  ['922a6b227c8e9f451f88edd1367200dcbf3533b5', 'test(fitness): make the member-access specifier case exercise its lookbehind (PC-145)', 'chore/pc-145-linux-only-guard', 'syntropic137-swe-mini[bot]', 4 * MINUTE],
  ['9fa95fb34ae8daed11c9a1aaf9f60b6537d32f2f', 'fix(fitness): catch bytes paths, interpolated code and every inotify form (PC-145)', 'chore/pc-145-linux-only-guard', 'syntropic137-swe-mini[bot]', 7 * MINUTE],
  ['f68c7d550963202710cefacc9493dd18ca29d0c3', 'docs(adr-058): codex reads the inlined content, not the imports (#1835)', 'fix/1835-codex-inline-instructions', 'syntropic137-swe-mini[bot]', 53 * MINUTE],
]

function recentEvents(): RecentEvent[] {
  const agent = COMMITS.map(([sha, message, branch, author, at], i): RecentEvent => ({
    time: ago(at),
    event_type: 'git_commit',
    session_id: null,
    execution_id: RUNS[i]?.id ?? null,
    phase_id: null,
    data: { git: { sha, repo: 'syntropic137', author, branch, message, operation: 'commit', files_changed: 1 }, workspace_id: `ws-${i}` },
  }))
  const webhook: RecentEvent = {
    time: ago(3 * 60 * MINUTE),
    event_type: 'git_commit',
    data: { commit_hash: 'a601fcbbf2d4c1e0b9a8f7e6d5c4b3a291807f6e', message: 'Merge pull request #1792 from syntropic137/fix/ui-feedback-settings-ignore-host-env', repository: 'syntropic137/syntropic137', branch: 'main', author: 'NeuralEmpowerment' },
  }
  return [...agent, webhook]
}

export const insightRoutes: FixtureRoute[] = [
  route('GET', '/events/recent', ({ query }): EventList => {
    const type = query.get('event_type')
    const limit = Number(query.get('limit') ?? 50)
    const rows = recentEvents().filter((e) => !type || e.event_type === type)
    return { events: rows.slice(0, limit), count: Math.min(rows.length, limit), has_more: rows.length > limit }
  }),
  route('GET', '/insights/contribution-heatmap', ({ query }): ContributionHeatmap => {
    const all = days()
    const start = query.get('start_date') ?? '2025-10-08'
    const end = query.get('end_date') ?? new Date(FIXTURE_NOW).toISOString().slice(0, 10)
    const inRange = all.filter((d) => d.date >= start && d.date <= end)
    return { metric: query.get('metric') ?? 'sessions', start_date: start, end_date: end, total: inRange.reduce((n, d) => n + d.count, 0), days: inRange }
  }),
]
