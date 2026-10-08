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
