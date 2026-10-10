/**
 * The app bar's budget: running, queued and the cap, in the server's words (PC-124).
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { ExecutionBudgetIndicator } from '../ExecutionBudgetIndicator'

const BUDGET = {
  running: 4,
  queued: 3,
  limit: 4,
  admission_paused: false,
  display: '4 running / 3 queued / cap 4',
}

function renderBudget(budget: typeof BUDGET | null) {
  return render(
    <MemoryRouter>
      <ExecutionBudgetIndicator budget={budget} />
    </MemoryRouter>,
  )
}

describe('ExecutionBudgetIndicator', () => {
  it('says how many run, how many wait, and the cap', () => {
    renderBudget(BUDGET)

    const link = screen.getByRole('link', { name: /Execution budget/ })
    expect(link.textContent).toContain('4 running / 3 queued / cap 4')
    // At 375px the sentence compacts; the numbers must survive it.
    expect(link.textContent).toContain('4/4 · 3 queued')
    expect(link.getAttribute('href')).toBe('/executions?status=queued')
  })

  it('renders nothing until the server has answered', () => {
    const { container } = renderBudget(null)

    expect(container.textContent).toBe('')
  })
})
