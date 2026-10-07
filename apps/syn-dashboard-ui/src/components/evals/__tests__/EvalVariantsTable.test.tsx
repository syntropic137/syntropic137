import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { LONG_MODEL, variant } from '../../../test/evalFixtures'
import { EvalVariantsStrip, EvalVariantsTable } from '../EvalVariantsTable'

describe('EvalVariantsTable (Compare)', () => {
  it('prints the server display strings verbatim, not a client reformat of the numbers', () => {
    render(<EvalVariantsTable variants={[variant()]} />)
    expect(screen.getByText('66.7% (2/3)')).toBeInTheDocument()
    expect(screen.getByText('$0.41 est.')).toBeInTheDocument()
    expect(screen.queryByText('$0.4123')).toBeNull()
  })

  it('shows one row per variant with its workflow and observed models', () => {
    render(
      <EvalVariantsTable
        variants={[
          variant(),
          variant({ workflow_id: 'wf-fast', models: ['claude-haiku-4-5', LONG_MODEL], pass_rate_display: '0% (0/1)' }),
        ]}
      />,
    )
    expect(screen.getAllByRole('row')).toHaveLength(3)
    expect(screen.getByText(`claude-haiku-4-5, ${LONG_MODEL}`)).toBeInTheDocument()
    expect(screen.getByText('0% (0/1)')).toBeInTheDocument()
  })

  it('says there is nothing to compare when no variant has run', () => {
    render(<EvalVariantsTable variants={[]} />)
    expect(screen.getByText(/nothing to compare/)).toBeInTheDocument()
  })

  it('lets long workflow ids and model ids break instead of overflowing', () => {
    render(<EvalVariantsTable variants={[variant({ models: [LONG_MODEL] })]} />)
    expect(screen.getByText(LONG_MODEL).closest('td')).toHaveClass('break-all')
    expect(screen.getByRole('table')).toHaveClass('table-fixed')
  })
})

describe('EvalVariantsStrip', () => {
  it('reads workflow and models to pass rate on one chip', () => {
    render(<EvalVariantsStrip variants={[variant()]} />)
    expect(screen.getByRole('listitem')).toHaveTextContent('wf-verifier · claude-sonnet-5 → 66.7% (2/3)')
  })
})
