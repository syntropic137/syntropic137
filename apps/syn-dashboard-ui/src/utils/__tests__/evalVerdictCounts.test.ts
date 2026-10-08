import { describe, expect, it } from 'vitest'

import type { EvalRun } from '../../api/evals'
import type { EvalTimelineState } from '../../hooks/useEvalTimeline'
import { evalRun, evalSummary, variant } from '../../test/evalFixtures'
import { variantKey } from '../evalVariants'
import { evalVerdictCounts, verdictBreakdown } from '../evalVerdictCounts'

const sonnet = variant({ run_count: 4 })
const haiku = variant({ workflow_id: 'wf-fast', models: ['claude-haiku-4-5'], run_count: 2 })

/** 4 sonnet runs (PASS, FAIL, ERROR, unscored) and 2 haiku runs (PASS, PASS). */
function history(): EvalRun[] {
  const haikuRun = (id: string) =>
    evalRun({ execution_id: id, workflow_id: 'wf-fast', models: [{ phase_id: 'a', model: 'claude-haiku-4-5' }], verdict: 'PASS' })
  return [
    evalRun({ execution_id: 's1', verdict: 'PASS' }),
    evalRun({ execution_id: 's2', verdict: 'FAIL' }),
    evalRun({ execution_id: 's3', verdict: 'ERROR' }),
    // Two phases on one model are still one model: the server's sorted unique set.
    evalRun({ execution_id: 's4', verdict: null, models: [{ phase_id: 'a', model: 'claude-sonnet-5' }, { phase_id: 'b', model: 'claude-sonnet-5' }] }),
    haikuRun('h1'),
    haikuRun('h2'),
  ]
}

function ready(runs: EvalRun[], total = runs.length): EvalTimelineState {
  return { kind: 'ready', runs, total }
}

describe('evalVerdictCounts', () => {
  it('counts every verdict over the eval and per variant when the history covers every run', () => {
    const counts = evalVerdictCounts(ready(history()), evalSummary({ run_count: 6, variants: [sonnet, haiku] }))
    expect(counts.eval).toEqual({ pass: 3, fail: 1, error: 1, unscored: 1 })
    expect(counts.byVariant?.get(variantKey(sonnet))).toEqual({ pass: 1, fail: 1, error: 1, unscored: 1 })
    expect(counts.byVariant?.get(variantKey(haiku))).toEqual({ pass: 2, fail: 0, error: 0, unscored: 0 })
  })

  it('is unavailable when the history is shorter than the eval, never a count of the runs it happened to read', () => {
    const runs = history()
    const e = evalSummary({ run_count: 2500, variants: [sonnet, haiku] })
    // Cut short by the timeline's bound: its own total says so.
    expect(evalVerdictCounts(ready(runs, 2500), e)).toEqual({ eval: null, byVariant: null })
    // A run added after the history was read: the eval says so.
    expect(evalVerdictCounts(ready(runs), e)).toEqual({ eval: null, byVariant: null })
    expect(evalVerdictCounts({ kind: 'loading' }, e)).toEqual({ eval: null, byVariant: null })
    expect(evalVerdictCounts({ kind: 'error', message: 'x' }, e)).toEqual({ eval: null, byVariant: null })
  })

  it("keeps the eval's counts but drops the variants' when the runs do not group into the server's variants", () => {
    const runs = history()
    const regrouped = evalSummary({ run_count: 6, variants: [variant({ run_count: 6 })] })
    expect(evalVerdictCounts(ready(runs), regrouped)).toEqual({ eval: { pass: 3, fail: 1, error: 1, unscored: 1 }, byVariant: null })
    const resized = evalSummary({ run_count: 6, variants: [variant({ run_count: 3 }), variant({ ...haiku, run_count: 3 })] })
    expect(evalVerdictCounts(ready(runs), resized).byVariant).toBeNull()
  })
})

describe('verdictBreakdown', () => {
  it('names every population separately, ERROR and unscored included', () => {
    expect(verdictBreakdown({ pass: 2, fail: 3, error: 1, unscored: 6 })).toBe('2 PASS · 3 FAIL · 1 ERROR · 6 unscored')
  })
})
