/**
 * Evals board sample data: six cases (one per caught bug) by four verifier
 * workflows. Each (case, verifier) pair is one eval tagged `case:<id>` and
 * `workflow:<id>`; the board pivots on those tags.
 */
import type { EvalRun, EvalRunListResponse, EvalSummary, EvalVariant, EvalVerdict } from '../resources/evals'
import { type FixtureRoute, notFound, route } from './define'
import { DAY, HOUR, after, ago, countBy, paginate } from './seed'

export const EVAL_CASES = [
  { id: 'shared-esp-stream', pr: 1574, sha: '6646da278d17', file: 'ExecutionRequestAggregate.py' },
  { id: 'execution-id-as-eval-id', pr: 1649, sha: '7047b1c3daf1', file: 'EvalAggregate.py' },
  { id: 'binary-artifact-minio-key', pr: 1652, sha: 'b2f680f00b4e', file: 'minio.py' },
  { id: 'codex-cost-limit', pr: 1654, sha: '123b25204fce', file: 'CodexStreamProcessor.py' },
  { id: 'live-commits-unvalidated-sha', pr: 1679, sha: '4c16d8f95fca', file: 'useEventFeed.ts' },
  { id: 'repo-privacy-ignores-app', pr: 1680, sha: '4c16d8f95fca', file: 'useRepoList.ts' },
] as const

export const EVAL_VERIFIERS = [
  { agent: 'claude', model: 'claude-opus-5-5', workflow: 'eval-verify-pinned-v1', agoMs: 5 * DAY },
  { agent: 'claude', model: 'claude-sonnet-5-5', workflow: 'eval-verify-pinned-sonnet-v1', agoMs: 1 * DAY },
  { agent: 'codex', model: 'gpt-5.6-sol', workflow: 'eval-verify-pinned-codex-v1', agoMs: 3 * DAY },
  { agent: 'codex', model: 'gpt-5.6-terra', workflow: 'eval-verify-pinned-codex-gpt-5-6-terra-v1', agoMs: 1 * HOUR },
] as const

type Cell = [verdict: EvalVerdict | null, cost: number, seconds: number]
const P: EvalVerdict = 'PASS'
const F: EvalVerdict = 'FAIL'
const E: EvalVerdict = 'ERROR'
const U = null

/** Rows are cases, columns verifiers (Evals board matrix). */
const MATRIX: Cell[][] = [
  [[P, 1.04, 372], [P, 0.52, 245], [P, 0.66, 228], [U, 0.61, 190]],
  [[P, 0.97, 341], [F, 0.47, 228], [P, 0.59, 204], [U, 0.55, 176]],
  [[P, 1.28, 418], [P, 0.61, 276], [F, 0.71, 246], [U, 0.68, 214]],
  [[P, 0.9, 305], [P, 0.44, 214], [P, 0.49, 187], [U, 0.52, 168]],
  [[P, 1.12, 388], [F, 0.55, 251], [F, 0.63, 219], [U, 0.58, 195]],
  [[F, 1.19, 402], [F, 0.58, 263], [E, 0.6, 231], [U, 0.64, 201]],
]

interface EvalRecord {
  summary: EvalSummary
  runs: EvalRun[]
}

type Case = (typeof EVAL_CASES)[number]
type VerifierDef = (typeof EVAL_VERIFIERS)[number]

/** Scorer evidence, worded as on the Evals board readout. */
function evidenceOf(verdict: EvalVerdict | null, c: Case, alt: boolean): string | null {
  if (verdict === P) return `Blocked the change. Names ${c.file} and matches every keyword group.`
  if (verdict === F) return alt ? `Blocked, but the report never names ${c.file}.` : `Approved the change. The defect in ${c.file} went unreported.`
  if (verdict === E) return 'The scorer could not read a verdict from the verify report.'
  return null
}

const SUITE = 'verifier-seed-v1'
const SUITE_VERSION = 'v2'

/**
 * Earlier runs per verifier column (oldest first), so Runs over time and
 * Compare have history. The board's matrix cell stays the latest run.
 */
const HISTORY: Record<number, EvalVerdict[]> = {
  0: [F, P, P, P],
  1: [P, F, P],
  2: [E, P],
}

function makeRun(evalId: string, c: Case, v: VerifierDef, verdict: EvalVerdict | null, cost: number, seconds: number, startedAt: string, n: number, version = 'v1', workflow: string = v.workflow): EvalRun {
  const completedAt = after(startedAt, seconds * 1000)
  return {
    execution_id: n === 0 ? `exec-${evalId}` : `exec-${evalId}-r${n}`,
    started_at: startedAt,
    completed_at: completedAt,
    status: 'completed',
    workflow_id: workflow,
    workflow_version: version,
    models: [{ phase_id: 'verify', model: v.model }],
    total_cost_usd: cost.toFixed(6),
    total_cost_display: `$${cost.toFixed(2)}`,
    duration_seconds: seconds,
    duration_display: `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, '0')}s`,
    verdict,
    score: verdict === 'PASS' ? 1 : verdict === 'FAIL' ? 0 : null,
    evidence_excerpt: evidenceOf(verdict, c, n % 2 === 1),
    scorer: verdict ? 'bug-caught-v1' : null,
    scorer_version: verdict ? '1' : null,
    scored_at: verdict ? completedAt : null,
  }
}

function variantOf(runs: EvalRun[], workflow: string, version: string, model: string): EvalVariant {
  const own = runs.filter((r) => r.workflow_id === workflow && r.workflow_version === version)
  const scored = own.filter((r) => r.verdict)
  const pass = own.filter((r) => r.verdict === 'PASS').length
  const avg = own.reduce((s, r) => s + Number(r.total_cost_usd), 0) / Math.max(1, own.length)
  const rate = scored.length ? pass / scored.length : null
  return {
    workflow_id: workflow,
    workflow_version: version,
    models: [model],
    run_count: own.length,
    pass_count: pass,
    pass_rate: rate,
    pass_rate_display: rate === null ? '—' : `${Math.round(rate * 100)}% (${pass}/${scored.length})`,
    avg_cost_usd: avg.toFixed(6),
    avg_cost_display: `$${avg.toFixed(2)}`,
    last_run_at: own[0]?.started_at ?? null,
  }
}

function build(): EvalRecord[] {
  const out: EvalRecord[] = []
  EVAL_CASES.forEach((c, ci) => {
    EVAL_VERIFIERS.forEach((v, vi) => {
      const [verdict, cost, seconds] = MATRIX[ci]![vi]!
      const evalId = `eval-${c.id}-${vi + 1}`
      const latestAt = ago(v.agoMs + ci * 11 * 60_000)
      const runs: EvalRun[] = [makeRun(evalId, c, v, verdict, cost, seconds, latestAt, 0)]
      const history = HISTORY[vi] ?? []
      history
        .slice()
        .reverse()
        .forEach((h, hi) => {
          const n = hi + 1
          const jitter = ((ci + n) % 3) * 0.07
          // The first case under opus was also run on a v2 of the workflow.
          const version = ci === 0 && vi === 0 && n === 2 ? 'v2' : 'v1'
          runs.push(makeRun(evalId, c, v, h, cost + jitter - 0.05, seconds + n * 17 - 20, ago(v.agoMs + n * 2 * DAY + ci * 13 * 60_000), n, version))
        })
      const variants = [...new Set(runs.map((r) => r.workflow_version))].map((ver) => variantOf(runs, v.workflow, ver ?? 'v1', v.model))
      const scored = runs.filter((r) => r.verdict)
      const pass = runs.filter((r) => r.verdict === 'PASS').length
      const rate = scored.length ? pass / scored.length : null
      out.push({
        runs,
        summary: {
          eval_id: evalId,
          name: `${SUITE} ${SUITE_VERSION}: ${c.id}`,
          goal: 'Does the verifier block a change that carries a known escaped bug, and name the defect and the file it lives in?',
          starting_workflow_id: v.workflow,
          baseline_repos: [{ repository: 'syntropic137/syntropic137', requested_ref: c.sha, commit_sha: `${c.sha}a16e16549cf77b0749b25d8e8040`.slice(0, 40) }],
          tags: [`case:${c.id}`, `${SUITE}:${SUITE_VERSION}:${v.workflow}`, `workflow:${v.workflow}`, `agent:${v.agent}`],
          frozen: vi === 3 || ci === 0,
          archived: false,
          created_at: ago(14 * DAY),
          updated_at: runs[0]!.completed_at ?? latestAt,
          run_count: runs.length,
          run_status_counts: { completed: runs.length },
          scored_count: scored.length,
          pass_rate: rate,
          pass_rate_display: rate === null ? '—' : `${Math.round(rate * 100)}% (${pass}/${scored.length})`,
          last_run_at: latestAt,
          last_verdict: verdict,
          variants,
        },
      })
    })
  })
  return out
}

export const EVALS: EvalRecord[] = build()

const find = (id: string) => EVALS.find((e) => e.summary.eval_id === id) ?? notFound('Eval')

export const evalRoutes: FixtureRoute[] = [
  route('GET', '/evals', ({ query }) => {
    const tag = query.get('tag')
    const rows = EVALS.map((e) => e.summary).filter((e) => !tag || e.tags.includes(tag))
    const page = paginate(rows, query, 100)
    return {
      evals: page.rows,
      total: page.total,
      page: page.page,
      page_size: page.page_size,
      status_counts: countBy(rows, (e) => e.last_verdict ?? 'UNSCORED'),
    }
  }),
  route('GET', '/evals/:evalId', ({ params }) => find(params.evalId!).summary),
  route('GET', '/evals/:evalId/runs', ({ params, query }): EvalRunListResponse => {
    const page = paginate(find(params.evalId!).runs, query, 50)
    return { items: page.rows, total: page.total, page: page.page, page_size: page.page_size }
  }),
]
