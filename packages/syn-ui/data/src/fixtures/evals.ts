/**
 * Evals board sample data: six cases (one per caught bug) by four verifier
 * workflows. Each (case, verifier) pair is one eval tagged `case:<id>` and
 * `workflow:<id>`; the board pivots on those tags.
 */
import type { EvalRun, EvalRunListResponse, EvalSummary, EvalVerdict } from '../resources/evals'
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

function build(): EvalRecord[] {
  const out: EvalRecord[] = []
  EVAL_CASES.forEach((c, ci) => {
    EVAL_VERIFIERS.forEach((v, vi) => {
      const [verdict, cost, seconds] = MATRIX[ci]![vi]!
      const startedAt = ago(v.agoMs + ci * 11 * 60_000)
      const completedAt = after(startedAt, seconds * 1000)
      const evalId = `eval-${c.id}-${vi + 1}`
      const run: EvalRun = {
        execution_id: `exec-${evalId}`,
        started_at: startedAt,
        completed_at: completedAt,
        status: 'completed',
        workflow_id: v.workflow,
        workflow_version: 'v1',
        models: [{ phase_id: 'verify', model: v.model }],
        total_cost_usd: cost.toFixed(6),
        total_cost_display: `$${cost.toFixed(2)}`,
        duration_seconds: seconds,
        duration_display: `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, '0')}s`,
        verdict,
        score: verdict === 'PASS' ? 1 : verdict === 'FAIL' ? 0 : null,
        evidence_excerpt: verdict ? `Checked ${c.file} at ${c.sha.slice(0, 7)} (PR #${c.pr}).` : null,
        scorer: verdict ? 'bug-caught-v1' : null,
        scorer_version: verdict ? '1' : null,
        scored_at: verdict ? completedAt : null,
      }
      const pass = verdict === 'PASS' ? 1 : 0
      const scored = verdict ? 1 : 0
      out.push({
        runs: [run],
        summary: {
          eval_id: evalId,
          name: `${c.id} · ${v.model}`,
          goal: `Does the verifier catch the bug fixed in PR #${c.pr} (${c.file})?`,
          starting_workflow_id: v.workflow,
          baseline_repos: [{ repository: 'syntropic137/syntropic137', requested_ref: c.sha, commit_sha: c.sha }],
          tags: [`case:${c.id}`, `workflow:${v.workflow}`, `agent:${v.agent}`],
          frozen: false,
          archived: false,
          created_at: ago(14 * DAY),
          updated_at: completedAt,
          run_count: 1,
          run_status_counts: { completed: 1 },
          scored_count: scored,
          pass_rate: scored ? pass : null,
          pass_rate_display: scored ? `${pass * 100}%` : '—',
          last_run_at: startedAt,
          last_verdict: verdict,
          variants: [
            {
              workflow_id: v.workflow,
              workflow_version: 'v1',
              models: [v.model],
              run_count: 1,
              pass_count: pass,
              pass_rate: scored ? pass : null,
              pass_rate_display: scored ? `${pass * 100}%` : '—',
              avg_cost_usd: cost.toFixed(6),
              avg_cost_display: `$${cost.toFixed(2)}`,
              last_run_at: startedAt,
            },
          ],
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
