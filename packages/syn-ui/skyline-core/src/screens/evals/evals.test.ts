import { describe, expect, it } from 'vitest'
import {
  agentOfModel,
  averageEvalCost,
  buildEvalBoard,
  runsTimeline,
  sameCaseSiblings,
  shortModel,
  sortEvalsByLastRun,
  suiteOf,
  tagValue,
  variantPassed,
  withLatestRun,
  workflowLabel,
  filterEvals,
  pageOf,
  recentVerdicts,
  NOT_SCORED,
  parseEvidence,
  runOutcome,
  verdictWord,
  type EvalLike,
} from './index'

const ev = (id: string, caseId: string, wf: string, model: string, verdict: string | null, last: string, cost = '0.5'): EvalLike => ({
  eval_id: id,
  name: `verifier-seed-v1 v2: ${caseId}`,
  tags: [`case:${caseId}`, `workflow:${wf}`],
  last_verdict: verdict,
  last_run_at: last,
  run_count: 1,
  variants: [{ workflow_id: wf, models: [model], avg_cost_usd: cost, run_count: 1 }],
})

/** A stable-id eval in the live shape: tags `case:` and `suite:` only, verifiers as variants. */
const stable = (id: string, caseId: string, variants: [wf: string, model: string, verdict: string | null, last: string, runs?: number, version?: string][]): EvalLike => ({
  eval_id: id,
  name: `verifier-seed: ${caseId}`,
  tags: [`case:${caseId}`, 'suite:verifier-seed'],
  starting_workflow_id: null,
  last_verdict: variants[0]?.[2] ?? null,
  last_run_at: variants[0]?.[3] ?? null,
  run_count: variants.reduce((n, v) => n + (v[4] ?? 1), 0),
  archived: false,
  variants: variants.map(([wf, model, verdict, last, runs = 1, version = '6.0.0']) => ({
    workflow_id: wf,
    workflow_version: version,
    models: model ? [model] : [],
    avg_cost_usd: '0.9',
    run_count: runs,
    last_run_at: last,
    last_verdict: verdict,
    stats: { median_cost_usd: '0.29' },
  })),
})

describe('verdict board from stable-id evals', () => {
  const T1 = '2026-10-08T01:00:00Z'
  const T2 = '2026-10-08T02:00:00Z'
  it('places one cell per case x variant workflow', () => {
    const b = buildEvalBoard([
      stable('s1', 'shared-esp-stream', [
        ['eval-verify-pinned-v1', 'claude-opus-5-5', 'PASS', T1],
        ['eval-verify-pinned-codex-v1', 'gpt-6.1-sol', 'FAIL', T2],
      ]),
    ])
    expect(b.cases.map((c) => c.id)).toEqual(['shared-esp-stream'])
    expect(b.verifiers.map((v) => v.id)).toEqual(['eval-verify-pinned-v1', 'eval-verify-pinned-codex-v1'])
    expect(b.cells['shared-esp-stream:eval-verify-pinned-v1']).toMatchObject({ verdict: 'pass', costUsd: 0.29, runs: 1 })
    expect(b.cells['shared-esp-stream:eval-verify-pinned-codex-v1']!.verdict).toBe('fail')
    expect(b.evalIds['shared-esp-stream:eval-verify-pinned-codex-v1']).toBe('s1')
    expect(b.workflows['shared-esp-stream:eval-verify-pinned-codex-v1']).toBe('eval-verify-pinned-codex-v1')
    expect(b.suite).toBe('verifier-seed')
  })

  it('lets a stable-id eval beat a newer legacy eval in the same cell', () => {
    const legacy = ev('l1', 'c1', 'wf-a', 'claude-opus-5-5', null, '2026-10-09T00:00:00Z')
    const b = buildEvalBoard([legacy, stable('s1', 'c1', [['wf-a', 'claude-opus-5-5', 'FAIL', T1]])])
    expect(b.evalIds['c1:wf-a']).toBe('s1')
    expect(b.cells['c1:wf-a']!.verdict).toBe('fail')
    expect(b.suite).toBeNull()
  })

  it('collapses versions of one workflow to the newest verdict and sums runs', () => {
    const b = buildEvalBoard([
      stable('s1', 'c1', [
        ['wf-a', '', 'FAIL', T1, 2, '3.0.0'],
        ['wf-a', 'claude-opus-5-5', 'PASS', T2, 3, '6.0.0'],
        ['wf-b', 'gpt-6-sol', null, T1, 0],
      ]),
    ])
    expect(b.cells['c1:wf-a']).toMatchObject({ verdict: 'pass', runs: 5 })
    expect(b.verifiers.map((v) => [v.id, v.model])).toEqual([['wf-a', 'claude-opus-5-5']])
  })

  it('skips archived evals and evals that never ran', () => {
    const archived = { ...ev('a', 'c1', 'wf-a', 'm', 'PASS', T1), archived: true }
    const never = { ...ev('n', 'c2', 'wf-b', 'm', null, ''), run_count: 0, last_run_at: null }
    const b = buildEvalBoard([archived, never])
    expect(b.cases).toEqual([])
    expect(b.verifiers).toEqual([])
  })

  it('never shows two identical column heads', () => {
    const b = buildEvalBoard([
      stable('s1', 'c1', [
        ['eval-verify-pinned-sdlc-lean-v1', 'gpt-6.1-sol', 'PASS', T1],
        ['eval-verify-pinned-sdlc-baseline-v1', 'gpt-6.1-sol', 'FAIL', T1],
        ['eval-verify-pinned-v1', 'claude-opus-5-5', 'PASS', T1],
      ]),
    ])
    const heads = b.verifiers.map((v) => `${v.agent} ${v.model}`)
    expect(new Set(heads).size).toBe(heads.length)
    expect(b.verifiers.map((v) => v.model)).toEqual(['gpt-6.1-sol · sdlc-lean', 'gpt-6.1-sol · sdlc-baseline', 'claude-opus-5-5'])
    expect(b.verifiers.map((v) => v.short)).toEqual(['sol · lean', 'sol · baseline', 'opus'])
    expect(workflowLabel('eval-verify-pinned-v1')).toBe('pinned')
    expect(workflowLabel('eval-verify-pinned-codex-gpt-6-luna-v1')).toBe('codex-gpt-6-luna')
    expect(workflowLabel('other-wf')).toBe('other-wf')
  })

  it('names a column with no observed model by its workflow', () => {
    const b = buildEvalBoard([stable('s1', 'c1', [['wf-x', '', 'ERROR', T1]])])
    expect(b.verifiers[0]).toMatchObject({ id: 'wf-x', model: 'wf-x', agent: 'Agent' })
    expect(b.cells['c1:wf-x']!.verdict).toBe('error')
  })
})

describe('evals screen helpers', () => {
  it('reads tags and models', () => {
    expect(tagValue(['case:a', 'workflow:b:c'], 'workflow')).toBe('b:c')
    expect(tagValue([], 'case')).toBeNull()
    expect(agentOfModel('claude-opus-5-5')).toBe('claude')
    expect(agentOfModel('gpt-5.6-sol')).toBe('codex')
    expect(agentOfModel('llama')).toBe('other')
    expect(shortModel('claude-sonnet-5-5')).toBe('sonnet')
    expect(shortModel('gpt-5.6-terra')).toBe('terra')
    expect(suiteOf('verifier-seed-v1 v2: x')).toBe('verifier-seed-v1 · v2')
    expect(suiteOf('plain')).toBeNull()
  })

  it('pivots evals into the verdict board', () => {
    const b = buildEvalBoard(
      [
        ev('1', 'c1', 'wf-a', 'claude-opus-5-5', 'PASS', '2026-10-01T00:00:00Z', '1.04'),
        ev('2', 'c1', 'wf-b', 'gpt-5.6-sol', 'FAIL', '2026-10-02T00:00:00Z'),
        ev('3', 'c2', 'wf-a', 'claude-opus-5-5', null, '2026-10-03T00:00:00Z'),
        ev('4', 'c2', 'wf-a', 'claude-opus-5-5', 'ERROR', '2026-09-01T00:00:00Z'),
        { ...ev('5', 'c3', 'wf-a', 'x', 'PASS', '2026-10-01T00:00:00Z'), tags: ['other'] },
      ],
      { evalHref: (id) => `/evals/${id}`, caseSub: (id) => `sub ${id}` },
    )
    expect(b.cases.map((c) => c.id)).toEqual(['c1', 'c2'])
    expect(b.cases[0]!.sub).toBe('sub c1')
    expect(b.verifiers.map((v) => [v.id, v.agent, v.short])).toEqual([
      ['wf-a', 'Claude', 'opus'],
      ['wf-b', 'Codex', 'sol'],
    ])
    expect(b.cells['c1:wf-a']).toMatchObject({ verdict: 'pass', costUsd: 1.04, evalHref: '/evals/1' })
    expect(b.cells['c1:wf-b']!.verdict).toBe('fail')
    // newest eval wins the cell
    expect(b.evalIds['c2:wf-a']).toBe('3')
    expect(b.cells['c2:wf-a']!.verdict).toBe('unscored')
    expect(b.suite).toBe('verifier-seed-v1 · v2')
  })

  it('sorts and finds siblings', () => {
    const a = ev('a', 'c1', 'w1', 'm', 'PASS', '2026-10-01T00:00:00Z')
    const b = ev('b', 'c1', 'w2', 'm', 'PASS', '2026-10-05T00:00:00Z')
    const c = { ...ev('c', 'c2', 'w1', 'm', 'PASS', ''), last_run_at: null }
    expect(sortEvalsByLastRun([a, c, b]).map((e) => e.eval_id)).toEqual(['b', 'a', 'c'])
    expect(sameCaseSiblings(a, [a, b, c]).map((e) => e.eval_id)).toEqual(['a', 'b'])
    expect(sameCaseSiblings({ ...a, tags: [] }, [a])).toEqual([])
  })

  it('lays out runs over time per variant', () => {
    const t = runsTimeline([
      { execution_id: 'r1', started_at: '2026-10-01T00:00:00Z', workflow_id: 'w', workflow_version: 'v1', models: [{ model: 'm1' }], verdict: 'PASS' },
      { execution_id: 'r2', started_at: '2026-10-03T00:00:00Z', workflow_id: 'w', workflow_version: 'v1', models: [{ model: 'm1' }], verdict: 'FAIL' },
      { execution_id: 'r3', started_at: '2026-10-02T00:00:00Z', workflow_id: 'w', workflow_version: 'v2', models: [{ model: 'm1' }, { model: 'm1' }], verdict: null },
    ])
    expect(t.lanes).toHaveLength(2)
    expect(t.lanes[0]!.label).toBe('w · m1')
    expect(t.lanes[0]!.points.map((p) => [p.executionId, p.x, p.verdict])).toEqual([
      ['r1', 4, 'pass'],
      ['r2', 96, 'fail'],
    ])
    expect(t.lanes[1]!.label).toBe('w v2 · m1')
    expect(t.lanes[1]!.points[0]!).toMatchObject({ x: 50, verdict: 'unscored' })
    expect(runsTimeline([{ execution_id: 'x', started_at: '2026-10-01T00:00:00Z' }]).lanes[0]!.points[0]!.x).toBe(50)
    expect(runsTimeline([]).start).toBeNull()
  })

  it('summarises variants and readout', () => {
    expect(variantPassed({ run_count: 5, pass_count: 3, pass_rate: 0.6 })).toEqual({ fraction: '3/5', fill: 60 })
    expect(variantPassed({ run_count: 1, pass_count: 0, pass_rate: null }).fill).toBeNull()
    expect(averageEvalCost([{ run_count: 1, avg_cost_usd: '1' }, { run_count: 3, avg_cost_usd: '0.5' }])).toBe('$0.63')
    expect(averageEvalCost([])).toBe('—')
    const cell = withLatestRun({ verdict: 'pass' }, { execution_id: 'e', verdict: null, duration_seconds: 190, total_cost_usd: '0.61' }, { runHref: '/x' })
    expect(cell).toMatchObject({ verdict: 'unscored', durationMs: 190_000, costUsd: 0.61, runHref: '/x' })
    expect(cell!.evidence).toMatch(/Not scored yet/)
    expect(withLatestRun(undefined, undefined)).toBeUndefined()
  })
})

describe('eval detail runs', () => {
  const LIVE =
    '## shared-esp-stream (defect)\n\n- run status: `completed`\n- review verdict: `blocked` (a pass needs `blocked`)\n- blocking findings: 1\n- expected file named: `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution_request/ExecutionRequestAggregate.py` '

  it('parses the scorer excerpt into facts', () => {
    expect(parseEvidence(LIVE)).toEqual({
      heading: 'shared-esp-stream (defect)',
      runStatus: 'completed',
      reviewVerdict: 'blocked',
      reviewNeeds: 'blocked',
      findings: 1,
      expectedFile: 'packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution_request/ExecutionRequestAggregate.py',
    })
    const truncated = parseEvidence('## c\n\n- run status: `failed`\n- review verdict: `none` (a pass needs `blocked`)\n- blocking findings: 0\n- expected file named: no (one of `a.py`, `packag')
    expect(truncated).toMatchObject({ runStatus: 'failed', reviewVerdict: 'none', findings: 0, expectedFile: 'no (one of a.py, packag' })
    expect(parseEvidence('Blocked the change. Names minio.py.')).toBeNull()
    expect(parseEvidence(null)).toBeNull()
    expect(parseEvidence('- blocking findings: lots')!.findings).toBeNull()
  })

  it('separates failed runs from scorer faults and never calls unscored a fail', () => {
    expect(runOutcome({ verdict: 'ERROR', status: 'failed' })).toEqual({ kind: 'run-failed', word: 'Run failed', verdict: 'unscored' })
    expect(runOutcome({ verdict: null, status: 'failed' }).kind).toBe('run-failed')
    expect(runOutcome({ verdict: 'ERROR', status: 'completed' })).toMatchObject({ kind: 'scorer-error', word: 'Scorer error', verdict: 'error' })
    expect(runOutcome({ verdict: null, status: 'completed' })).toMatchObject({ kind: 'unscored', word: 'Not scored yet' })
    expect(runOutcome({ verdict: 'FAIL', status: 'failed' }).kind).toBe('fail')
    expect(runOutcome({ verdict: 'PASS' }).word).toBe('Pass')
    expect(verdictWord('unscored')).toBe(NOT_SCORED)
    expect(verdictWord('error')).toBe('Error')
    expect(verdictWord('fail')).toBe('Fail')
  })

  it('compare reads unscored as not scored, not 0/1', () => {
    expect(variantPassed({ run_count: 1, pass_count: 0, pass_rate: null })).toEqual({ fraction: 'Not scored yet', fill: null })
    expect(variantPassed({ run_count: 4, pass_count: 2, pass_rate: 2 / 3 })).toEqual({ fraction: '2/3', fill: 67 })
    expect(variantPassed({ run_count: 2, pass_count: 0, pass_rate: 0 })).toEqual({ fraction: '0 passed', fill: 0 })
  })
})

describe('evals list from one load', () => {
  const a = ev('a', 'shared-esp-stream', 'wf-a', 'm', 'PASS', '2026-10-01T00:00:00Z')
  const b = ev('b', 'codex-cost-limit', 'wf-b', 'm', 'FAIL', '2026-10-02T00:00:00Z')
  it('filters by exact tag or substring of name and tags', () => {
    expect(filterEvals([a, b], '').map((e) => e.eval_id)).toEqual(['a', 'b'])
    expect(filterEvals([a, b], 'case:codex-cost-limit').map((e) => e.eval_id)).toEqual(['b'])
    expect(filterEvals([a, b], 'ESP').map((e) => e.eval_id)).toEqual(['a'])
    expect(filterEvals([a, b], 'wf-')).toHaveLength(2)
    expect(filterEvals([a, b], 'nope')).toEqual([])
  })
  it('pages client-side', () => {
    const rows = Array.from({ length: 45 }, (_, i) => i)
    expect(pageOf(rows, 1, 20)).toEqual({ rows: rows.slice(0, 20), pageCount: 3, from: 1 })
    expect(pageOf(rows, 3, 20).rows).toEqual([40, 41, 42, 43, 44])
    expect(pageOf([], 1, 20)).toEqual({ rows: [], pageCount: 1, from: 1 })
  })
  it('builds sparklines from variant verdicts, oldest first', () => {
    const s = stable('s', 'c', [
      ['w1', 'm', 'FAIL', '2026-10-08T02:00:00Z'],
      ['w2', 'm', 'PASS', '2026-10-08T01:00:00Z'],
      ['w3', 'm', null, '2026-10-08T03:00:00Z', 0],
    ])
    expect(recentVerdicts(s)).toEqual(['pass', 'fail'])
    expect(recentVerdicts({ ...a, variants: [] })).toEqual(['pass'])
    expect(recentVerdicts({ ...a, run_count: 0 })).toEqual([])
  })
})
