/**
 * Overview (/) screen logic: turns the metrics, heatmap, executions and
 * workflows responses into the plain values the Main and PhoneOverview
 * boards render. No DOM, no Svelte; the page only fetches and passes data.
 */
import type { SkylineDay } from '../../geometry/skyline'
import { formatInteger, formatPercent } from '../../format/number'
import { formatTokens, TOKEN_SERIES } from '../../format/tokens'
import { toNumber } from '../../format/shared'
import { statusKind } from '../../patterns/status'

/** A heatmap bucket as the API sends it (structural, so data never leaks in here). */
export interface HeatmapBucketInput {
  date: string
  count?: number
  breakdown?: Record<string, number> | null
}

const num = (v: unknown): number => {
  const n = toNumber(v as number | string | null | undefined)
  return n === null ? 0 : n
}

/**
 * Heatmap buckets to Skyline days. `count` is the fallback for sessions;
 * days with no tokens at all get `tokens: null` so the readout says
 * "No tokens recorded". Sorted by date.
 */
export function heatmapToSkylineDays(buckets: readonly HeatmapBucketInput[] | null | undefined): SkylineDay[] {
  if (!buckets) return []
  return buckets
    .map((b): SkylineDay => {
      const br = b.breakdown ?? {}
      const tokens = {
        input: num(br.input_tokens),
        output: num(br.output_tokens),
        cacheWrite: num(br.cache_creation_tokens),
        cacheRead: num(br.cache_read_tokens),
      }
      const anyTokens = tokens.input + tokens.output + tokens.cacheWrite + tokens.cacheRead > 0
      const cost = br.cost_usd
      return {
        date: b.date.slice(0, 10),
        sessions: 'sessions' in br ? num(br.sessions) : num(b.count),
        executions: num(br.executions),
        commits: num(br.commits),
        costUsd: cost === undefined || cost === null ? null : num(cost),
        tokens: anyTokens ? tokens : null,
      }
    })
    .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0))
}

/** Days with at least one session. */
export function activeDayCount(days: readonly SkylineDay[]): number {
  return days.filter((d) => d.sessions > 0).length
}

/** Distinct years present in the days, ascending, always including `currentYear`. */
export function skylineYears(days: readonly SkylineDay[], currentYear: number): number[] {
  const set = new Set<number>([currentYear])
  for (const d of days) if (d.sessions > 0) set.add(Number(d.date.slice(0, 4)))
  return [...set].filter((y) => Number.isFinite(y)).sort((a, b) => a - b)
}

const WORDS = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten']

/** "Two" for 2, "12" for 12; capitalised for the start of a sentence. */
export function countWord(n: number): string {
  return n >= 0 && n < WORDS.length ? WORDS[n]! : formatInteger(n)
}

export interface HeadlineInput {
  /** Executions running right now. */
  running: number
  /** Recent runs that failed and need a look. */
  needsLook: number
}

/** The two-line hero: "All quiet." / "Two runs need a look." */
export function overviewHeadline({ running, needsLook }: HeadlineInput): { lead: string; follow: string } {
  const lead = running > 0 ? `${countWord(running)} ${running === 1 ? 'run' : 'runs'} working.` : 'All quiet.'
  const follow =
    needsLook > 0
      ? `${countWord(needsLook)} ${needsLook === 1 ? 'run needs' : 'runs need'} a look.`
      : 'Nothing needs a look.'
  return { lead, follow }
}

/** Minimal execution row shape the overview reads. */
export interface OverviewRunInput {
  workflow_execution_id: string
  workflow_name: string
  status: string
  started_at?: string | null
  completed_at?: string | null
}

/**
 * Runs for the attention chips: failed (and interrupted) runs among the
 * recent ones, newest first, at most `limit`.
 */
export function attentionRuns<T extends OverviewRunInput>(runs: readonly T[], limit = 2): T[] {
  return runs.filter((r) => statusKind(r.status) === 'failed').slice(0, limit)
}

export function runningCount(runs: readonly OverviewRunInput[]): number {
  return runs.filter((r) => statusKind(r.status) === 'running').length
}

export interface StatusCountsInput {
  completed?: number
  failed?: number
  cancelled?: number
  interrupted?: number
  running?: number
  not_started?: number
}

/** Outcome Ring counts. Interrupted runs count as cancelled (both stopped short). */
export function outcomeCounts(c: StatusCountsInput | null | undefined): { completed: number; failed: number; cancelled: number } {
  return {
    completed: num(c?.completed),
    failed: num(c?.failed),
    cancelled: num(c?.cancelled) + num(c?.interrupted),
  }
}

/** "50 completed · 23 failed · 2 cancelled" (compact: "50 done · ..."). Zero parts are dropped. */
export function outcomeLine(c: { completed: number; failed: number; cancelled: number }, compact = false): string {
  const parts: string[] = []
  if (c.completed) parts.push(`${formatInteger(c.completed)} ${compact ? 'done' : 'completed'}`)
  if (c.failed) parts.push(`${formatInteger(c.failed)} failed`)
  if (c.cancelled) parts.push(`${formatInteger(c.cancelled)} cancelled`)
  return parts.length ? parts.join(' · ') : 'none yet'
}

export interface TokenTotalsInput {
  total_input_tokens?: number | null
  total_output_tokens?: number | null
  total_cache_creation_tokens?: number | null
  total_cache_read_tokens?: number | null
}

export interface TokenMixPart {
  key: 'cacheRead' | 'cacheWrite' | 'output' | 'input'
  label: string
  /** CSS custom property for the series colour. */
  token: string
  value: number
  display: string
  /** "90.9%" */
  share: string
  /** Flex weight for the bar; never below 0.8% of the total so a sliver stays visible. */
  flex: number
}

/** Token Mix card: the four series in TOKEN_SERIES order, with shares of the total. */
export function tokenMix(m: TokenTotalsInput | null | undefined): { total: number; parts: TokenMixPart[] } {
  const values = {
    cacheRead: num(m?.total_cache_read_tokens),
    cacheWrite: num(m?.total_cache_creation_tokens),
    output: num(m?.total_output_tokens),
    input: num(m?.total_input_tokens),
  }
  const total = values.cacheRead + values.cacheWrite + values.output + values.input
  const parts = TOKEN_SERIES.map((s) => {
    const key = s.key as TokenMixPart['key']
    const value = values[key]
    return {
      key,
      label: s.label,
      token: s.token,
      value,
      display: formatTokens(value),
      share: total > 0 ? formatPercent(value / total, 1) : '0.0%',
      flex: total > 0 ? Math.max(value, total * 0.008) : 0,
    }
  }).filter((p) => p.value > 0)
  return { total, parts }
}

export interface WorkflowRunsInput {
  id: string
  name: string
  runs_count: number
}

export interface TopWorkflow {
  id: string
  name: string
  runs: string
  /** Bar width as a percentage of the busiest workflow. */
  percent: number
}

/** Most-run workflows: busiest first, workflows never run are left out. */
export function topWorkflows(workflows: readonly WorkflowRunsInput[] | null | undefined, limit = 5): TopWorkflow[] {
  if (!workflows) return []
  const sorted = workflows.filter((w) => w.runs_count > 0).sort((a, b) => b.runs_count - a.runs_count || a.name.localeCompare(b.name))
  const top = sorted.slice(0, limit)
  const max = top[0]?.runs_count ?? 0
  return top.map((w) => ({
    id: w.id,
    name: w.name,
    runs: `${formatInteger(w.runs_count)} ${w.runs_count === 1 ? 'run' : 'runs'}`,
    percent: max > 0 ? Math.max(2, Math.round((w.runs_count / max) * 100)) : 0,
  }))
}

/** Distinct repositories across triggers. */
export function distinctRepoCount(rows: readonly { repository?: string | null }[] | null | undefined): number {
  if (!rows) return 0
  return new Set(rows.map((r) => r.repository).filter((r): r is string => !!r)).size
}

/** "watching GitHub events on 2 repos" (compact: "watching 2 repos"). */
export function triggerLine(repos: number, compact = false): string {
  if (repos === 0) return compact ? 'none watching yet' : 'nothing watching yet'
  const r = `${formatInteger(repos)} ${repos === 1 ? 'repo' : 'repos'}`
  return compact ? `watching ${r}` : `watching GitHub events on ${r}`
}
