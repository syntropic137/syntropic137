/**
 * Trend rows for GET /evals/{id}/trend and GET /workflows/{id}/trend.
 *
 * Eval rows are the Eval board's renderVals() sample (RAW): 28 runs over 30
 * days by four verifiers, judged by claude-opus-5-5, with the verify prompt
 * changed on day 18. Workflow rows are the catalog runs with durations shaped
 * by the Workflows board's trendOf(), so each card reads Faster, Slower or
 * Steady by the same rule the board used.
 */
import type { EvalVerdict } from '../resources/evals'
import type { DefinitionChange, EvalTrendResponse, EvalTrendRow, WorkflowTrendResponse, WorkflowTrendRow } from '../resources/trends'
import { RUNS, WORKFLOWS, type CatalogRun, type CatalogWorkflow } from './catalog'
import { type FixtureRoute, notFound, route } from './define'
import { costDisplay, durationDisplay, paginate } from './seed'
import { EVALS } from './evals'
import { EXTRA_WORKFLOWS } from './workflowDetails'

const MODELS = ['claude-opus-5-5', 'claude-sonnet-5-5', 'gpt-5.6-sol', 'gpt-5.6-terra'] as const
/** USD per million tokens, per verifier (board RATE): tokens = cost / rate. */
const RATE = [9.0, 3.0, 2.5, 2.0]
const JUDGE = 'claude-opus-5-5'
/** Day 0 of the board's chart: Sep 8, 2026 (UTC). */
const DAY0 = Date.UTC(2026, 8, 8)
const DAY = 86_400_000
/** The verify prompt changed on day 18 (board NOTES). */
const CHANGE_DAY = 18

type Raw = [day: number, verifier: number, verdict: EvalVerdict | 'UNSCORED', cost: number, seconds: number, score: number | null]

/** Board RAW, verbatim apart from the judge column (always JUDGE when scored). */
const RAW: Raw[] = [
  [0, 0, 'PASS', 1.21, 452, 82], [4, 0, 'PASS', 1.18, 431, 85], [8, 0, 'FAIL', 1.25, 470, 61], [12, 0, 'PASS', 1.16, 418, 84],
  [17, 0, 'PASS', 1.09, 392, 88], [21, 0, 'PASS', 1.06, 381, 90], [25, 0, 'PASS', 1.02, 366, 91], [29, 0, 'PASS', 1.04, 372, 92],
  [1, 1, 'FAIL', 0.49, 241, 48], [5, 1, 'FAIL', 0.51, 236, 55], [9, 1, 'PASS', 0.5, 247, 72], [13, 1, 'FAIL', 0.53, 252, 63],
  [16, 1, 'FAIL', 0.52, 240, 66], [19, 1, 'PASS', 0.5, 233, 78], [22, 1, 'PASS', 0.52, 238, 84], [26, 1, 'PASS', 0.51, 229, 87],
  [28, 1, 'PASS', 0.52, 245, 89], [2, 2, 'PASS', 0.55, 262, 80], [7, 2, 'PASS', 0.58, 255, 78], [11, 2, 'FAIL', 0.61, 249, 64],
  [15, 2, 'PASS', 0.63, 240, 76], [20, 2, 'FAIL', 0.66, 236, 62], [24, 2, 'PASS', 0.69, 231, 73], [27, 2, 'FAIL', 0.71, 228, 58],
  [23, 3, 'PASS', 0.62, 214, 79], [25, 3, 'FAIL', 0.6, 201, 66], [27, 3, 'PASS', 0.59, 196, 81], [29, 3, 'UNSCORED', 0.61, 190, null],
]

const money = (cost: number, seconds: number | null, tokens: number) => ({
  cost_usd: cost.toFixed(6),
  cost_is_lower_bound: false,
  cost_display: costDisplay(cost),
  duration_seconds: seconds,
  duration_is_lower_bound: false,
  duration_display: durationDisplay(seconds),
  tokens,
})

const WORKFLOW = ['eval-verify-pinned-v1', 'eval-verify-pinned-sonnet-v1', 'eval-verify-pinned-codex-v1', 'eval-verify-pinned-codex-gpt-5-6-terra-v1']

function evalRow([day, v, verdict, cost, seconds, score]: Raw): EvalTrendRow {
  return {
    execution_id: `exec-trend-${v + 1}-${day}`,
    // Verifiers run two hours apart on a shared day, in board order.
    date: new Date(DAY0 + day * DAY + (9 + v * 2) * 3_600_000).toISOString(),
    workflow_id: WORKFLOW[v]!,
    workflow_version: 'v1',
    eval_definition_version: day >= CHANGE_DAY ? '2' : '1',
    verifier_model: MODELS[v]!,
    observed_models: [MODELS[v]!],
    judge_model: score === null ? null : JUDGE,
    score,
    verdict: verdict === 'UNSCORED' ? null : verdict,
    ...money(cost, seconds, Math.round((cost / RATE[v]!) * 1e6)),
  }
}

/** Newest first, as the API sends them. */
export const EVAL_TREND_ROWS: EvalTrendRow[] = RAW.map(evalRow).sort((a, b) => (b.date ?? '').localeCompare(a.date ?? ''))

const EVAL_CHANGES: DefinitionChange[] = [
  { definition_version: '1', changed_at: new Date(DAY0 - 2 * DAY).toISOString(), kind: 'created' },
  { definition_version: '2', changed_at: new Date(DAY0 + CHANGE_DAY * DAY).toISOString(), kind: 'updated' },
]

// ---- workflows ------------------------------------------------------------

/** Board trendOf(): slope -3..3 from the name and phase count; each step is 6% of duration. */
function boardSlope(w: CatalogWorkflow): number {
  const k = w.name.length + w.phases.length
  return ((k * 37) % 7) - 3
}

/** Board wobble, minus its own least-squares line so it never moves the fitted trend. */
function wobble(n: number, k: number): number[] {
  const raw = Array.from({ length: n }, (_, j) => ((j * 13 + k * 7) % 5) - 2)
  const mx = (n - 1) / 2
  const my = raw.reduce((a, v) => a + v, 0) / n
  const sxx = raw.reduce((a, _, j) => a + (j - mx) ** 2, 0)
  const slope = sxx ? raw.reduce((a, v, j) => a + (j - mx) * (v - my), 0) / sxx : 0
  return raw.map((v, j) => v - my - slope * (j - mx))
}

/** Durations from S to S x (1 - slope x 6%), oldest first, with the board's wobble. */
function shapedDurations(w: CatalogWorkflow, finished: readonly CatalogRun[]): number[] {
  const n = finished.length
  if (n < 3) return finished.map((r) => r.seconds)
  const base = finished.reduce((a, r) => a + r.seconds, 0) / n
  const change = (-boardSlope(w) * 6) / 100
  const wob = wobble(n, w.name.length + w.phases.length)
  return finished.map((_, j) => Math.round((base * (1 + (change * j) / (n - 1)) + wob[j]! * 0.02 * base) * 10) / 10)
}

/** Workflow board Performance sample: each phase's share of a run (96 : 188 : 134 seconds). */
const PHASE_SHARE: Record<string, readonly number[]> = { 'research-workflow': [0.23, 0.45, 0.32] }

/** A phase's seconds: its share of the run, null for phases the run never reached. */
function phaseSeconds(w: CatalogWorkflow, r: CatalogRun, d: number | null, k: number): number | null {
  if (d === null || (r.status !== 'completed' && k > r.done)) return null
  const share = PHASE_SHARE[w.id]?.[k] ?? 1 / w.phases.length
  return Math.round(d * share * 10) / 10
}

/** Definition changes inside a workflow's run history (the board's "v2 published" marker). */
function workflowChanges(w: CatalogWorkflow): DefinitionChange[] {
  const created: DefinitionChange = { definition_version: 'v1', changed_at: new Date(DAY0 - 60 * DAY).toISOString(), kind: 'created' }
  if (w.id !== 'research-workflow') return [created]
  const dates = RUNS.filter((r) => r.workflowId === w.id).map((r) => Date.parse(r.startedAt)).sort((a, b) => a - b)
  const mid = (dates[0]! + dates.at(-1)!) / 2
  return [created, { definition_version: 'v2', changed_at: new Date(mid).toISOString(), kind: 'updated' }]
}

function workflowRows(w: CatalogWorkflow): WorkflowTrendRow[] {
  const runs = RUNS.filter((r) => r.workflowId === w.id).sort((a, b) => a.startedAt.localeCompare(b.startedAt))
  const finished = runs.filter((r) => r.status !== 'running')
  const durations = shapedDurations(w, finished)
  const shaped = new Map(finished.map((r, j) => [r.id, durations[j]!]))
  return runs
    .map((r): WorkflowTrendRow => {
      const d = shaped.get(r.id) ?? null
      return {
        execution_id: r.id,
        date: r.startedAt,
        status: r.status,
        workflow_version: 'v1',
        ...money(r.cost, d, r.tokens),
        phase_durations: w.phases.map((p, k) => ({ phase_id: p.id, phase_name: p.name, duration_seconds: phaseSeconds(w, r, d, k) })),
      }
    })
    .reverse()
}

const definition = (changes: DefinitionChange[]) => ({
  definition_version: changes.at(-1)?.definition_version ?? null,
  definition_changed_at: changes.at(-1)?.changed_at ?? null,
  definition_changes: changes,
})

export const trendRoutes: FixtureRoute[] = [
  route('GET', '/evals/:evalId/trend', ({ params, query }): EvalTrendResponse => {
    const e = EVALS.find((x) => x.summary.eval_id === params.evalId) ?? notFound('Eval')
    const page = paginate(EVAL_TREND_ROWS, query, 50)
    return { eval_id: e.summary.eval_id, items: page.rows, total: page.total, page: page.page, page_size: page.page_size, ...definition(EVAL_CHANGES) }
  }),
  route('GET', '/workflows/:workflowId/trend', ({ params, query }): WorkflowTrendResponse => {
    const w = [...WORKFLOWS, ...EXTRA_WORKFLOWS].find((x) => x.id === params.workflowId) ?? notFound('Workflow')
    const page = paginate(workflowRows(w), query, 50)
    return { workflow_id: w.id, items: page.rows, total: page.total, page: page.page, page_size: page.page_size, ...definition(workflowChanges(w)) }
  }),
]
