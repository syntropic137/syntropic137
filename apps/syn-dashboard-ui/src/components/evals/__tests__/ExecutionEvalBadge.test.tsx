import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { ExecutionEvalRun } from '../../../api/evals'
import { ExecutionEvalBadge } from '../ExecutionEvalBadge'

function evalRun(overrides: Partial<ExecutionEvalRun> = {}): ExecutionEvalRun {
  return {
    eval_id: 'eval-7f3a',
    eval_name: 'verifier-seed: case-1',
    association_kind: 'launched',
    verdict: 'FAIL',
    score: 0,
    scored_at: '2026-10-07T12:00:00Z',
    ...overrides,
  }
}

function renderBadge(value: ExecutionEvalRun | null | undefined) {
  return render(
    <MemoryRouter>
      <ExecutionEvalBadge evalRun={value} />
    </MemoryRouter>,
  )
}

describe('ExecutionEvalBadge', () => {
  it('links to the eval by id and names it', () => {
    renderBadge(evalRun())
    const link = screen.getByTestId('execution-eval-badge')
    expect(link).toHaveAttribute('href', '/evals/eval-7f3a')
    expect(link).toHaveTextContent('verifier-seed: case-1')
  })

  it("shows the run's current verdict", () => {
    renderBadge(evalRun({ verdict: 'PASS' }))
    expect(screen.getByText('PASS')).toHaveAttribute('data-verdict', 'PASS')
  })

  it('says Unscored until a scorer records a verdict', () => {
    renderBadge(evalRun({ verdict: null, score: null, scored_at: null }))
    expect(screen.getByText('Unscored')).toBeInTheDocument()
  })

  it('falls back to the eval id when the name is not projected yet', () => {
    renderBadge(evalRun({ eval_name: null }))
    expect(screen.getByTestId('execution-eval-badge')).toHaveTextContent('eval-7f3a')
  })

  it('marks a run attached after launch', () => {
    renderBadge(evalRun({ association_kind: 'attached' }))
    expect(screen.getByText('attached')).toBeInTheDocument()
  })

  it.each([null, undefined])('renders nothing for an execution in no eval (%s)', (value) => {
    const { container } = renderBadge(value)
    expect(container).toBeEmptyDOMElement()
  })
})
