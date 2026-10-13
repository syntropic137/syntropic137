/**
 * Evals board sample data, in the two shapes the live API serves:
 *
 * - legacy: six cases (one per caught bug) by four verifier workflows. Each
 *   (case, verifier) pair is one eval tagged `case:<id>` and `workflow:<id>`.
 * - stable id: one eval per case (`verifier-seed: <case>`, tags `case:` and
 *   `suite:` only, no starting workflow) whose variants are the verifiers.
 *   Every scored run on the VPS lives in this shape.
 *
 * Plus archived legacy evals that never ran, which the board must skip.
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
    last_verdict: own[0]?.verdict ?? null,
    stats: statsOf(own),
  }
}

const median = (xs: number[]): number | null => {
  if (!xs.length) return null
  const s = [...xs].sort((a, b) => a - b)
  const mid = Math.floor(s.length / 2)
  return s.length % 2 ? s[mid]! : (s[mid - 1]! + s[mid]!) / 2
}
const money = (n: number | null) => (n === null ? '—' : n < 0.01 ? '<$0.01' : `$${n.toFixed(2)}`)

/** EvalRunStatsResponse over runs, as the API derives it. */
function statsOf(runs: EvalRun[]): EvalSummary['stats'] {
  const secs = median(runs.map((r) => r.duration_seconds).filter((d): d is number => typeof d === 'number'))
  const cost = median(runs.map((r) => Number(r.total_cost_usd)).filter((c) => Number.isFinite(c)))
  const passes = runs.filter((r) => r.verdict === 'PASS').length
  const total = runs.reduce((s, r) => s + Number(r.total_cost_usd ?? 0), 0)
  const perPass = passes ? total / passes : null
  return {
    median_duration_seconds: secs,
    median_duration_display: secs === null ? '—' : `${Math.floor(secs / 60)}m ${Math.round(secs % 60)}s`,
    incomplete_duration_count: 0,
    median_cost_usd: cost === null ? null : cost.toFixed(6),
    median_cost_display: money(cost),
    incomplete_cost_count: 0,
    cost_per_pass_usd: perPass === null ? null : perPass.toFixed(6),
    cost_per_pass_display: money(perPass),
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
          stats: statsOf(runs),
        },
      })
    })
  })
  return out
}

/** Stable-id verifiers: the variants of each `verifier-seed: <case>` eval. */
export const STABLE_VERIFIERS = [
  { model: 'claude-opus-5-5', workflow: 'eval-verify-pinned-v1' },
  { model: 'claude-sonnet-5-5', workflow: 'eval-verify-pinned-sonnet-v1' },
  { model: 'gpt-6.1-sol', workflow: 'eval-verify-pinned-sdlc-lean-v1' },
  { model: 'gpt-6.1-sol', workflow: 'eval-verify-pinned-sdlc-baseline-v1' },
] as const

type StableRun = [verifier: number, verdict: EvalVerdict | null, status: 'completed' | 'failed', cost: number, seconds: number, review: string, findings: number, hoursAgo: number]

interface StableCase {
  id: string
  control: boolean
  sha: string
  file: string
  runs: StableRun[]
}

const STABLE_CASES: StableCase[] = [
  {
    id: 'shared-esp-stream',
    control: false,
    sha: '6646da278d17a16e16549cf77b0749b25d8e8040',
    file: 'packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution_request/ExecutionRequestAggregate.py',
    runs: [
      [1, P, 'completed', 0.4962644, 163, 'blocked', 1, 3],
      [0, P, 'completed', 1.0821, 312, 'blocked', 1, 4],
      [2, F, 'completed', 0.2911, 151, 'none', 1, 5],
      [3, E, 'failed', 0, 41, 'none', 0, 6],
      [1, F, 'completed', 0.4711, 170, 'certified', 0, 30],
    ],
  },
  {
    id: 'clean-merged-change',
    control: true,
    sha: 'b5ef79107cbd44d4e2b9dd9a1cbee8c57ee1be80',
    file: '',
    runs: [
      [0, P, 'completed', 0.5888464, 124, 'certified', 0, 2],
      [1, F, 'completed', 0.4407, 151, 'blocked', 2, 2.5],
      [2, P, 'completed', 0.1700748, 170, 'certified', 0, 3.5],
      [3, null, 'completed', 0.2104, 162, 'certified', 0, 4.5],
    ],
  },
]

/** The scorer's markdown excerpt, in the live `eval_suite.py` format (truncated as the API truncates it). */
function stableEvidence(c: StableCase, run: StableRun): string {
  const [, , status, , , review, findings] = run
  const want = c.control ? 'certified' : 'blocked'
  const lines = [`## ${c.id}${status === 'failed' ? '' : c.control ? ' (control)' : ' (defect)'}`, '', `- run status: \`${status}\``, `- review verdict: \`${review}\` (a pass needs \`${want}\`)`, `- blocking findings: ${findings}`]
  if (!c.control) lines.push(review === 'blocked' && findings > 0 ? `- expected file named: \`${c.file}\` ` : `- expected file named: no (one of \`${c.file}\`, \`packag`)
  return lines.join('\n')
}

function stableRun(c: StableCase, run: StableRun, n: number): EvalRun {
  const [vi, verdict, status, cost, seconds, , , hoursAgo] = run
  const v = STABLE_VERIFIERS[vi]!
  const startedAt = ago(hoursAgo * HOUR)
  const completedAt = after(startedAt, seconds * 1000)
  return {
    execution_id: `exec-stable-${c.id}-${n}`,
    started_at: startedAt,
    completed_at: completedAt,
    status,
    workflow_id: v.workflow,
    workflow_version: '6.0.0',
    models: status === 'failed' ? [] : [{ phase_id: 'verify', model: v.model }],
    total_cost_usd: cost.toFixed(7),
    total_cost_display: money(cost),
    duration_seconds: seconds,
    duration_display: `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, '0')}s`,
    verdict,
    score: verdict === 'PASS' ? 1 : verdict === 'FAIL' ? 0 : null,
    evidence_excerpt: verdict ? stableEvidence(c, run) : null,
    scorer: verdict ? 'eval_suite.py' : null,
    scorer_version: verdict ? '3' : null,
    scored_at: verdict ? completedAt : null,
  }
}

function buildStable(): EvalRecord[] {
  return STABLE_CASES.map((c) => {
    const runs = c.runs.map((r, i) => stableRun(c, r, i)).sort((a, b) => Date.parse(b.started_at ?? '') - Date.parse(a.started_at ?? ''))
    const variants = STABLE_VERIFIERS.map((v) => variantOf(runs, v.workflow, '6.0.0', v.model)).filter((v) => v.run_count > 0)
    const scored = runs.filter((r) => r.verdict)
    const pass = runs.filter((r) => r.verdict === 'PASS').length
    const rate = scored.length ? pass / scored.length : null
    return {
      runs,
      summary: {
        eval_id: `eval-stable-${c.id}`,
        name: `verifier-seed: ${c.id}`,
        goal: 'Does the verifier block a change that carries a known escaped bug, naming the defect and the file it lives in, and certify a merged change that has no known defect?',
        starting_workflow_id: null,
        baseline_repos: [{ repository: 'syntropic137/syntropic137', requested_ref: c.sha, commit_sha: c.sha }],
        tags: [`case:${c.id}`, 'suite:verifier-seed'],
        frozen: true,
        archived: false,
        created_at: ago(2 * DAY),
        updated_at: runs[0]!.completed_at ?? runs[0]!.started_at!,
        run_count: runs.length,
        run_status_counts: countBy(runs, (r) => r.status),
        scored_count: scored.length,
        pass_rate: rate,
        pass_rate_display: rate === null ? '—' : `${Math.round(rate * 100)}%`,
        last_run_at: runs[0]!.started_at ?? null,
        last_verdict: runs[0]!.verdict ?? null,
        variants,
        stats: statsOf(runs),
      },
    }
  })
}

/** Archived legacy evals with no runs: on the VPS, 34 of 88 look like this. */
function buildArchived(): EvalRecord[] {
  return EVAL_CASES.slice(0, 3).map((c) => {
    const wf = 'eval-verify-pinned-codex-v1'
    return {
      runs: [],
      summary: {
        eval_id: `eval-archived-${c.id}`,
        name: `${SUITE} v1: ${c.id}`,
        goal: 'Does the verifier block a change that carries a known escaped bug, and name the defect and the file it lives in?',
        starting_workflow_id: wf,
        baseline_repos: [{ repository: 'syntropic137/syntropic137', requested_ref: c.sha, commit_sha: `${c.sha}a16e16549cf77b0749b25d8e8040`.slice(0, 40) }],
        tags: [`case:${c.id}`, `${SUITE}:v1:${wf}`, `workflow:${wf}`],
        frozen: true,
        archived: true,
        created_at: ago(20 * DAY),
        updated_at: ago(19 * DAY),
        run_count: 0,
        run_status_counts: {},
        scored_count: 0,
        pass_rate: null,
        pass_rate_display: '—',
        last_run_at: null,
        last_verdict: null,
        variants: [],
        stats: statsOf([]),
      },
    }
  })
}

export const EVALS: EvalRecord[] = [...build(), ...buildStable(), ...buildArchived()]

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
