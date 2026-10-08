import { describe, expect, it } from 'vitest'

import { stats, variant, withoutStats } from '../../test/evalFixtures'
import { MIN_JUDGED_FOR_BEST, bestVariantKey, sortVariants, variantKey } from '../evalVariants'

describe('bestVariantKey', () => {
  it('is null with fewer than two judged variants: best of one is not a comparison', () => {
    expect(bestVariantKey([variant(), variant({ workflow_id: 'wf-err', pass_rate: null })])).toBeNull()
    expect(bestVariantKey([])).toBeNull()
  })

  it('breaks a pass-rate tie on the cheaper median run, then on more judged runs', () => {
    const dear = variant({ workflow_id: 'wf-dear', pass_rate: 1, stats: stats({ median_cost_usd: '2.00' }) })
    const cheap = variant({ workflow_id: 'wf-cheap', pass_rate: 1, stats: stats({ median_cost_usd: '0.20' }) })
    expect(bestVariantKey([dear, cheap])).toBe(variantKey(cheap))

    // run_count is the other way round: unscored and ERROR runs are not judgements.
    const few = variant({ workflow_id: 'wf-few', pass_rate: 1, run_count: 40, stats: stats({ pass_count: 3, fail_count: 0 }) })
    const many = variant({ workflow_id: 'wf-many', pass_rate: 1, run_count: 9, stats: stats({ pass_count: 9, fail_count: 0 }) })
    expect(bestVariantKey([few, many])).toBe(variantKey(many))
  })

  it('never crowns a variant judged fewer than MIN_JUDGED_FOR_BEST times, however cheap', () => {
    // The live shape: one PASS judged out of many runs, cheaper than the variant with evidence.
    const lucky = variant({
      workflow_id: 'wf-lucky',
      pass_rate: 1,
      run_count: 8,
      stats: stats({ median_cost_usd: '0.10', pass_count: 1, fail_count: 0, error_count: 2, unscored_count: 5 }),
    })
    const proven = variant({ workflow_id: 'wf-proven', pass_rate: 0.75, stats: stats({ median_cost_usd: '0.90', pass_count: 3, fail_count: 1 }) })
    const other = variant({ workflow_id: 'wf-other', pass_rate: 0.5, stats: stats({ pass_count: 2, fail_count: 2 }) })
    expect(MIN_JUDGED_FOR_BEST).toBe(3)
    expect(bestVariantKey([lucky, proven, other])).toBe(variantKey(proven))
    // With only one variant left that has enough judged runs, there is no comparison to win.
    expect(bestVariantKey([lucky, proven])).toBeNull()
  })

  it('has no best when the API sent no stats: a judged count cannot be guessed from a rounded rate', () => {
    const a = withoutStats(variant({ workflow_id: 'a', pass_rate: 1 }))
    const b = withoutStats(variant({ workflow_id: 'b', pass_rate: 0.5 }))
    expect(bestVariantKey([a, b])).toBeNull()
  })
})

describe('sortVariants', () => {
  it('sorts by median duration either way and keeps an unknown duration last both ways', () => {
    const vs = [
      variant({ workflow_id: 'b', stats: stats({ median_duration_seconds: 300 }) }),
      variant({ workflow_id: 'none', stats: stats({ median_duration_seconds: null }) }),
      variant({ workflow_id: 'a', stats: stats({ median_duration_seconds: 60 }) }),
    ]
    expect(sortVariants(vs, 'duration', 'asc').map((v) => v.workflow_id)).toEqual(['a', 'b', 'none'])
    expect(sortVariants(vs, 'duration', 'desc').map((v) => v.workflow_id)).toEqual(['b', 'a', 'none'])
  })

  it('sorts variants from an API with no stats last on duration and cost, instead of throwing', () => {
    const legacy = withoutStats(variant({ workflow_id: 'legacy' }))
    const vs = [
      legacy,
      variant({ workflow_id: 'dear', stats: stats({ median_cost_usd: '2.00', median_duration_seconds: 600 }) }),
      variant({ workflow_id: 'cheap', stats: stats({ median_cost_usd: '0.10', median_duration_seconds: 60 }) }),
    ]
    expect(sortVariants(vs, 'cost', 'asc').map((v) => v.workflow_id)).toEqual(['cheap', 'dear', 'legacy'])
    expect(sortVariants(vs, 'cost', 'desc').map((v) => v.workflow_id)).toEqual(['dear', 'cheap', 'legacy'])
    expect(sortVariants(vs, 'duration', 'asc').map((v) => v.workflow_id)).toEqual(['cheap', 'dear', 'legacy'])
  })

  it('does not reorder its input', () => {
    const vs = [variant({ workflow_id: 'b', run_count: 1 }), variant({ workflow_id: 'a', run_count: 5 })]
    sortVariants(vs, 'runs', 'desc')
    expect(vs.map((v) => v.workflow_id)).toEqual(['b', 'a'])
  })
})
