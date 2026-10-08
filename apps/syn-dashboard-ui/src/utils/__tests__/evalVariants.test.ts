import { describe, expect, it } from 'vitest'

import { stats, variant } from '../../test/evalFixtures'
import { bestVariantKey, sortVariants, variantKey } from '../evalVariants'

describe('bestVariantKey', () => {
  it('is null with fewer than two judged variants: best of one is not a comparison', () => {
    expect(bestVariantKey([variant(), variant({ workflow_id: 'wf-err', pass_rate: null })])).toBeNull()
    expect(bestVariantKey([])).toBeNull()
  })

  it('breaks a pass-rate tie on the cheaper median run, then on more runs', () => {
    const dear = variant({ workflow_id: 'wf-dear', pass_rate: 1, stats: stats({ median_cost_usd: '2.00' }) })
    const cheap = variant({ workflow_id: 'wf-cheap', pass_rate: 1, stats: stats({ median_cost_usd: '0.20' }) })
    expect(bestVariantKey([dear, cheap])).toBe(variantKey(cheap))

    const few = variant({ workflow_id: 'wf-few', pass_rate: 1, run_count: 1 })
    const many = variant({ workflow_id: 'wf-many', pass_rate: 1, run_count: 9 })
    expect(bestVariantKey([few, many])).toBe(variantKey(many))
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

  it('does not reorder its input', () => {
    const vs = [variant({ workflow_id: 'b', run_count: 1 }), variant({ workflow_id: 'a', run_count: 5 })]
    sortVariants(vs, 'runs', 'desc')
    expect(vs.map((v) => v.workflow_id)).toEqual(['b', 'a'])
  })
})
