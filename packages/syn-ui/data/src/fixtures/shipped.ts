/**
 * GET /metrics/shipped: the Main board's "Shipped by agents" sample.
 * 14 days: 1,204 commits (+38%), 73 PRs opened (+24%), 61 merged (+27%),
 * an 84% merge rate (+5 pts) and 9 repos (+3). Daily series follow the
 * board's bar heights, scaled so they sum to the totals (two quiet days at
 * index 3 and 9). 7 and 30 days scale the same shape.
 *
 * Test hook: set `globalThis.synFixtureShippedUnavailable` to tile keys
 * (e2e addInitScript) and those tiles come back null with a reason, as a
 * server that cannot answer them would send.
 */
import type { ShippedMetric, ShippedMetricsResponse } from '../resources/shipped'
import { type FixtureRoute, route } from './define'
import { DAY, FIXTURE_NOW } from './seed'

type TileKey = 'commits' | 'prs_opened' | 'prs_merged' | 'merge_rate' | 'repos_touched'

/** Board bar heights, oldest first (0 = the board's empty bar). */
const SHAPE: Record<TileKey, number[]> = {
  commits: [26, 35, 28, 0, 8, 45, 50, 39, 62, 0, 16, 71, 89, 100],
  prs_opened: [25, 42, 33, 0, 8, 50, 58, 42, 67, 0, 17, 75, 92, 100],
  prs_merged: [20, 40, 30, 0, 10, 50, 60, 40, 70, 0, 20, 80, 90, 100],
  /** Daily merge rate in percent. */
  merge_rate: [80, 96, 90, 0, 100, 83, 86, 80, 88, 0, 100, 89, 82, 83],
  /** Distinct repos each day. */
  repos_touched: [2, 3, 2, 0, 1, 3, 4, 3, 4, 0, 1, 5, 5, 6],
}

/** [total, previous total, delta_display] for 14 days. */
const BOARD: Record<TileKey, [number, number, string]> = {
  commits: [1204, 872, '+38%'],
  prs_opened: [73, 59, '+24%'],
  prs_merged: [61, 48, '+27%'],
  merge_rate: [84, 79, '+5 pts'],
  repos_touched: [9, 6, '+3'],
}

const REASON: Record<TileKey, string> = {
  commits: 'This server does not record git commits.',
  prs_opened: 'This server does not record pull requests.',
  prs_merged: 'This server does not record pull requests.',
  merge_rate: 'This server does not record pull requests.',
  repos_touched: 'This server does not record repositories.',
}

const REPOS = ['syntropic137/syntropic137', 'syntropic137/event-sourcing-platform', 'syntropic137/agentic-workspace', 'syntropic137/syntropic137-claude-plugin', 'syntropic137/syntropic137-landing-page', 'syntropic137/sandbox_syn-engineer-beta', 'syntropic137/orchestrator-bin', 'syntropic137/syn-docs', 'syntropic137/design-system']

const BY_WORKFLOW = [
  { workflow_id: 'research-workflow', name: 'Research Workflow', commits: 712, prs_merged: 38 },
  { workflow_id: 'pr-review', name: 'PR Review', commits: 286, prs_merged: 14 },
  { workflow_id: 'skill-probe', name: 'Skill Probe', commits: 206, prs_merged: 9 },
]

/** Integers in proportion to `weights` that sum to `total` (largest remainder). */
function spread(weights: readonly number[], total: number): number[] {
  const sum = weights.reduce((a, b) => a + b, 0)
  if (sum === 0) return weights.map(() => 0)
  const raw = weights.map((w) => (w / sum) * total)
  const out = raw.map(Math.floor)
  const order = raw.map((r, i) => [r - Math.floor(r), i] as const).sort((a, b) => b[0] - a[0])
  const missing = total - out.reduce((a, b) => a + b, 0)
  for (let k = 0; k < missing; k++) out[order[k % order.length]![1]]! += 1
  return out
}

/** The 14-day shape repeated back to fill `days`, newest day last. */
function shapeFor(key: TileKey, days: number): number[] {
  const s = SHAPE[key]
  return Array.from({ length: days }, (_, i) => s[(((s.length - days + i) % s.length) + s.length) % s.length]!)
}

const isoDay = (t: number) => new Date(t).toISOString().slice(0, 10)

function unavailableKeys(): ReadonlySet<string> {
  const hook = (globalThis as { synFixtureShippedUnavailable?: unknown }).synFixtureShippedUnavailable
  return new Set(Array.isArray(hook) ? hook.filter((k): k is string => typeof k === 'string') : [])
}

function metric(key: TileKey, days: number, dates: string[]): ShippedMetric {
  const [total14, prev14, display] = BOARD[key]
  const scale = days / 14
  const percent = key === 'merge_rate'
  const total = percent || key === 'repos_touched' ? total14 : Math.round(total14 * scale)
  const previous = percent || key === 'repos_touched' ? prev14 : Math.round(prev14 * scale)
  const shape = shapeFor(key, days)
  const values = percent || key === 'repos_touched' ? shape : spread(shape, total)
  return {
    total,
    previous_total: previous,
    delta: total - previous,
    delta_display: days === 14 ? display : null,
    series: dates.map((date, i) => ({ date, value: values[i] ?? 0 })),
  }
}

export function shippedMetrics(daysParam: number, workflowId: string | null): ShippedMetricsResponse {
  const days = daysParam === 7 || daysParam === 30 ? daysParam : 14
  const today = Date.UTC(new Date(FIXTURE_NOW).getUTCFullYear(), new Date(FIXTURE_NOW).getUTCMonth(), new Date(FIXTURE_NOW).getUTCDate())
  const from = today - (days - 1) * DAY
  const dates = Array.from({ length: days }, (_, i) => isoDay(from + i * DAY))
  const off = unavailableKeys()
  const reasons: Partial<Record<TileKey, string>> = {}
  const tile = (key: TileKey): ShippedMetric | null => {
    if (!off.has(key)) return metric(key, days, dates)
    reasons[key] = REASON[key]
    return null
  }
  const body: ShippedMetricsResponse = {
    window: { days, from: `${isoDay(from)}T00:00:00Z`, to: `${isoDay(today)}T23:59:59Z` },
    previous: { from: `${isoDay(from - days * DAY)}T00:00:00Z`, to: `${isoDay(from - DAY)}T23:59:59Z` },
    commits: tile('commits'),
    prs_opened: tile('prs_opened'),
    prs_merged: tile('prs_merged'),
    merge_rate: tile('merge_rate'),
    repos_touched: tile('repos_touched'),
    reasons,
    repos: REPOS,
    by_workflow: workflowId ? BY_WORKFLOW.filter((w) => w.workflow_id === workflowId) : BY_WORKFLOW,
  }
  return body
}

export const shippedRoutes: FixtureRoute[] = [
  route('GET', '/metrics/shipped', ({ query }): ShippedMetricsResponse => shippedMetrics(Number(query.get('days') ?? 14), query.get('workflow_id'))),
]
