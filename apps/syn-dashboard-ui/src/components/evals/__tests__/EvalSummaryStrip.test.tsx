import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { evalSummary, stats, verdictCounts, withoutStats } from '../../../test/evalFixtures'
import { EvalSummaryStrip } from '../EvalSummaryStrip'

describe('EvalSummaryStrip', () => {
  it('wraps the coverage-qualified figures instead of clipping them, so a phone reads them without hover', () => {
    const qualified = {
      median_duration_display: '20m 0s (excl. 1 incomplete)',
      median_cost_display: '$0.41 (excl. 1 incomplete)',
      cost_per_pass_display: '>=$1.00 (partial)',
    }
    render(<EvalSummaryStrip e={evalSummary({ stats: stats(qualified) })} counts={verdictCounts()} />)

    for (const text of Object.values(qualified)) {
      const value = screen.getByText(text)
      expect(value).not.toHaveClass('truncate')
      expect(value).toHaveClass('break-words')
    }
  })

  it('shows how many runs were PASS, FAIL, ERROR and unscored under "Runs scored"', () => {
    const counts = verdictCounts({ pass: 2, fail: 0, error: 1, unscored: 5 })
    render(<EvalSummaryStrip e={evalSummary({ run_count: 8, scored_count: 3 })} counts={counts} />)
    expect(screen.getByText('3 / 8')).toBeInTheDocument()
    expect(screen.getByText('2 PASS · 0 FAIL · 1 ERROR · 5 unscored')).toBeInTheDocument()
  })

  it('says the verdict counts are unavailable rather than guessing them when the run history is incomplete', () => {
    render(<EvalSummaryStrip e={evalSummary({ run_count: 8, scored_count: 3 })} counts={null} />)
    expect(screen.getByText('3 / 8')).toBeInTheDocument()
    expect(screen.getByText('verdict counts unavailable')).toBeInTheDocument()
    expect(screen.queryByText(/PASS · /)).toBeNull()
  })

  it('labels cost per PASS as scored spend with unscored runs left out', () => {
    render(<EvalSummaryStrip e={evalSummary()} counts={verdictCounts()} />)
    expect(screen.getByText(/scored-run spend \(ERROR included\) ÷ PASS runs; unscored excluded/)).toBeInTheDocument()
  })

  it('says stats are unavailable when an older API sends none, and still shows pass rate and runs', () => {
    const counts = verdictCounts({ pass: 1, fail: 1, error: 0, unscored: 2 })
    render(<EvalSummaryStrip e={withoutStats(evalSummary({ run_count: 4, scored_count: 2 }))} counts={counts} />)
    expect(screen.getByText(/Stats unavailable/)).toBeInTheDocument()
    expect(screen.getByText('2 / 4')).toBeInTheDocument()
    expect(screen.getByText('1 PASS · 1 FAIL · 0 ERROR · 2 unscored')).toBeInTheDocument()
    expect(screen.queryByText('Cost per PASS')).toBeNull()
  })
})
