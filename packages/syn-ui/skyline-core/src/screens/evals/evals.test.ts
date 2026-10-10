import { describe, expect, it } from 'vitest'
import {
  agentOfModel,
  averageEvalCost,
  evalFigures,
  variantStats,
  buildEvalBoard,
  latestRunCosts,
  latestRuns,
  evalRunKey,
  runsTimeline,
  sameCaseSiblings,
  sameCaseVerifiers,
  shortModel,
  sortEvalsByLastRun,
  suiteOf,
  tagValue,
  variantPassed,
  withLatestRun,
  workflowLabel,
  evidenceSummary,
  filterEvals,
  pageOf,
  recentVerdicts,
  NOT_SCORED,
  parseEvidence,
  runOutcome,
  verdictWord,
  type EvalLike,
} from './index'
import { cellKey, verifierFooter } from '../../patterns/verdict'

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

describe('board readout evidence', () => {
  it('summarises a scorer excerpt in one sentence', () => {
    expect(evidenceSummary('## c (defect)\n\n- run status: `completed`\n- review verdict: `blocked` (a pass needs `blocked`)\n- blocking findings: 1\n- expected file named: `a/b.py` ')).toBe(
      'Review verdict blocked (pass needs blocked). 1 blocking finding. Expected file: a/b.py.',
    )
    expect(evidenceSummary('- run status: `failed`\n- blocking findings: 0')).toBe('Run failed. 0 blocking findings.')
    expect(evidenceSummary('free text')).toBe('free text')
    expect(evidenceSummary(null)).toBeNull()
  })
})

describe('board cell cost is the latest run cost (parity 2026-10-09: 27 of 99 cells showed the median)', () => {
  // clean-remote-source under eval-verify-pinned-codex-v1: runs $0.16 (latest, PASS), $0.22, $0.33; median $0.22.
  const e = stable('eval-clean', 'clean-remote-source', [['eval-verify-pinned-codex-v1', 'gpt-6.1-sol', 'PASS', '2026-10-08T15:09:12Z', 3]])
  const rows = [
    { workflow_id: 'eval-verify-pinned-codex-v1', started_at: '2026-10-07T10:00:00Z', total_cost_usd: '0.2200000', eval: { eval_id: 'eval-clean' } },
    { workflow_id: 'eval-verify-pinned-codex-v1', started_at: '2026-10-08T15:09:12Z', total_cost_usd: '0.1600000', eval: { eval_id: 'eval-clean' } },
    { workflow_id: 'eval-verify-pinned-codex-v1', started_at: '2026-10-06T10:00:00Z', total_cost_usd: '0.3300000', eval: { eval_id: 'eval-clean' } },
    { workflow_id: 'other', started_at: '2026-10-09T00:00:00Z', total_cost_usd: '9', eval: null },
  ]
  it('picks the newest run per eval and workflow', () => {
    const costs = latestRunCosts(rows)
    expect(costs.size).toBe(1)
    const board = buildEvalBoard([e], { costOf: (id, wf) => costs.get(`${id}\u0000${wf}`) })
    expect(Object.values(board.cells)[0]).toMatchObject({ verdict: 'pass', costUsd: 0.16 })
  })
  it('shows no cost rather than another run\'s when the runs have not loaded', () => {
    expect(Object.values(buildEvalBoard([e], { costOf: () => undefined }).cells)[0]!.costUsd).toBeNull()
    expect(Object.values(buildEvalBoard([e]).cells)[0]!.costUsd).toBe(0.29)
  })
})

describe('same case, other verifiers (parity 2026-10-09: luna tile showed the eval-level Pass)', () => {
  // eval-dbb1269d…: eval last_verdict PASS (opus); variants luna FAIL, codex PASS, opus PASS.
  const e = {
    eval_id: 'eval-dbb1269d51fb4b68b5e258523e4e2d68',
    name: 'verifier-seed: repo-name-collision-skipped-clone',
    tags: ['case:repo-name-collision-skipped-clone', 'suite:verifier-seed'],
    last_verdict: 'PASS',
    last_run_at: '2026-10-08T15:25:08Z',
    run_count: 3,
    variants: [
      { workflow_id: 'eval-verify-pinned-codex-gpt-6-luna-v1', workflow_version: '6.0.0', models: ['gpt-6-luna'], run_count: 1, last_verdict: 'FAIL', last_run_at: '2026-10-08T15:14:22Z', avg_cost_display: '<$0.01' },
      { workflow_id: 'eval-verify-pinned-codex-v1', workflow_version: '6.0.0', models: ['gpt-6.1-sol'], run_count: 1, last_verdict: 'PASS', last_run_at: '2026-10-08T15:09:12Z', avg_cost_display: '$0.17' },
      { workflow_id: 'eval-verify-pinned-v1', workflow_version: '6.0.0', models: ['claude-opus-5-5'], run_count: 1, last_verdict: 'PASS', last_run_at: '2026-10-08T15:25:08Z', avg_cost_display: '$0.59' },
      { workflow_id: 'eval-verify-pinned-v1', workflow_version: '5.0.0', models: ['claude-opus-5'], run_count: 2, last_verdict: 'FAIL', last_run_at: '2026-10-01T00:00:00Z', avg_cost_display: '$0.70' },
    ],
  }
  it('gives each verifier its own verdict and model', () => {
    const tiles = sameCaseVerifiers(e, [e])
    expect(tiles.map((t) => [t.models[0], t.verdict, t.avgCost])).toEqual([
      ['gpt-6-luna', 'fail', '<$0.01'],
      ['gpt-6.1-sol', 'pass', '$0.17'],
      ['claude-opus-5-5', 'pass', '$0.59'],
    ])
    expect(tiles[2]!.runs).toBe(3)
    expect(tiles.some((t) => t.current)).toBe(false)
  })
  it('keeps one eval-level tile for an eval with no variants', () => {
    const legacy: EvalLike = { eval_id: 'old', name: 'x', tags: ['case:repo-name-collision-skipped-clone'], last_verdict: 'PASS', run_count: 0, starting_workflow_id: 'wf-old' }
    expect(sameCaseVerifiers(e, [e, legacy]).at(-1)).toMatchObject({ workflowId: 'wf-old', verdict: 'unscored', current: false })
  })
})

describe('verdict board footer time per verifier (parity-2 #3: blank for 7 of 8 verifiers)', () => {
  const e = stable('eval-two', 'two-verifiers', [
    ['eval-verify-pinned-codex-v1', 'gpt-6.1-sol', 'PASS', '2026-10-08T15:09:12Z', 1],
    ['eval-verify-pinned-v1', 'claude-opus-5-5', 'FAIL', '2026-10-08T15:10:00Z', 1],
  ])
  const rows = [
    { workflow_id: 'eval-verify-pinned-codex-v1', started_at: '2026-10-08T15:09:12Z', total_cost_usd: '0.16', duration_seconds: 161, eval: { eval_id: 'eval-two' } },
    { workflow_id: 'eval-verify-pinned-codex-v1', started_at: '2026-10-07T15:09:12Z', total_cost_usd: '0.30', duration_seconds: 999, eval: { eval_id: 'eval-two' } },
    { workflow_id: 'eval-verify-pinned-v1', started_at: '2026-10-08T15:10:00Z', total_cost_usd: '0.70', duration_seconds: 187, eval: { eval_id: 'eval-two' } },
  ]
  it('gives every column an average time from its latest runs, without a selection', () => {
    const latest = latestRuns(rows)
    const board = buildEvalBoard([e], {
      costOf: (id, wf) => latest.get(evalRunKey(id, wf))?.costUsd,
      durationOf: (id, wf) => latest.get(evalRunKey(id, wf))?.durationMs,
    })
    const footers = board.verifiers.map((v) => verifierFooter(board.cases.map((c) => board.cells[cellKey(c.id, v.id)])))
    expect(footers.map((f) => f.averages)).toEqual(['$0.16 · 2m 41s', '$0.70 · 3m 7s'])
  })
  it('keeps the board duration when the readout enriches a selected cell', () => {
    expect(withLatestRun({ verdict: 'pass', durationMs: 161_000 }, { execution_id: 'e', verdict: 'PASS', duration_seconds: 158 })!.durationMs).toBe(161_000)
  })
})

describe('eval detail medians (parity-2 #7: median duration, median cost and cost per pass were dropped)', () => {
  // repo-name-collision on the VPS: stats median 131.76 s / $0.185 / cost per pass $0.3227.
  const stats = { median_duration_display: '2m 11s', median_cost_display: '$0.19', cost_per_pass_display: '$0.32' }
  it("shows the API's stats in the header, verbatim", () => {
    expect(evalFigures({ run_count: 4, scored_count: 4, pass_rate_display: '75%', stats })).toEqual([
      { label: 'Runs', value: '4' },
      { label: 'Scored', value: '4' },
      { label: 'Pass rate', value: '75%' },
      { label: 'Median duration', value: '2m 11s' },
      { label: 'Median cost', value: '$0.19' },
      { label: 'Cost per pass', value: '$0.32' },
    ])
    expect(evalFigures({ run_count: 0 })).toHaveLength(3)
  })
  it('gives each variant row its median duration and cost', () => {
    expect(variantStats({ stats: { ...stats, median_duration_display: '2m 14s (excl. 1 incomplete)' } })).toEqual({ duration: '2m 14s (excl. 1 incomplete)', cost: '$0.19' })
    expect(variantStats({})).toEqual({ duration: '—', cost: '—' })
  })
})
