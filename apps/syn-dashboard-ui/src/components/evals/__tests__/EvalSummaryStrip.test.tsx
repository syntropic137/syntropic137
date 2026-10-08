import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { evalSummary, stats } from '../../../test/evalFixtures'
import { EvalSummaryStrip } from '../EvalSummaryStrip'

describe('EvalSummaryStrip', () => {
  it('wraps the coverage-qualified figures instead of clipping them, so a phone reads them without hover', () => {
    const qualified = {
      median_duration_display: '20m 0s (excl. 1 incomplete)',
      median_cost_display: '$0.41 (excl. 1 incomplete)',
      cost_per_pass_display: '>=$1.00 (partial)',
    }
    render(<EvalSummaryStrip e={evalSummary({ stats: stats(qualified) })} />)

    for (const text of Object.values(qualified)) {
      const value = screen.getByText(text)
      expect(value).not.toHaveClass('truncate')
      expect(value).toHaveClass('break-words')
    }
  })
})
