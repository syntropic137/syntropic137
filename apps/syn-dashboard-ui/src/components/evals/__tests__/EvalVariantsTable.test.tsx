import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { EvalVariant } from '../../../api/evals'
import { LONG_MODEL, countsFor, stats, variant, withoutStats } from '../../../test/evalFixtures'
import type { VerdictCounts } from '../../../utils/evalVerdictCounts'
import { EvalVariantsStrip, EvalVariantsTable } from '../EvalVariantsTable'

/** The table with counts from a complete run history (3 judged each unless `by` says otherwise); `by={null}` when incomplete. */
function Compare({ variants, by = {} }: { variants: EvalVariant[]; by?: Record<string, Partial<VerdictCounts>> | null }) {
  return <EvalVariantsTable variants={variants} counts={by === null ? null : countsFor(variants, by)} />
}

describe('EvalVariantsTable (Compare)', () => {
  it('prints the server display strings verbatim, not a client reformat of the numbers', () => {
    render(<Compare variants={[variant()]} />)
    expect(screen.getByText('66.7% (2/3)')).toBeInTheDocument()
    expect(screen.getByText('20m med.')).toBeInTheDocument()
    expect(screen.getByText('$0.41 med.')).toBeInTheDocument()
    expect(screen.getByText('>=$0.62 (partial) / PASS')).toBeInTheDocument()
    expect(screen.queryByText('$0.4123')).toBeNull()
  })

  it("shows the variant's last verdict, and its run count without an ERROR-inflated pass denominator", () => {
    render(<Compare variants={[variant({ run_count: 5, pass_count: 2, last_verdict: 'ERROR' })]} />)
    const [, row] = screen.getAllByRole('row')
    expect(within(row).getByText('ERROR')).toHaveAttribute('data-verdict', 'ERROR')
    expect(within(row).getByText('5')).toBeInTheDocument()
    expect(within(row).queryByText('2/5')).toBeNull()
  })

  it('marks the best variant: highest pass rate, ERROR-only (no rate) never wins', () => {
    render(
      <Compare
        variants={[
          variant({ workflow_id: 'wf-errors', pass_rate: null, pass_rate_display: '—', last_verdict: 'ERROR' }),
          variant({ workflow_id: 'wf-low', pass_rate: 0.25, pass_rate_display: '25%' }),
          variant({ workflow_id: 'wf-high', pass_rate: 0.9, pass_rate_display: '90%' }),
        ]}
      />,
    )
    const best = document.querySelectorAll('tr[data-best]')
    expect(best).toHaveLength(1)
    expect(best[0]).toHaveTextContent('wf-high')
    expect(within(best[0] as HTMLElement).getByText('Best · 3 judged')).toBeInTheDocument()
  })

  it('crowns no variant whose pass rate rests on fewer than three judged runs', () => {
    render(
      <Compare
        variants={[
          variant({ workflow_id: 'wf-lucky', pass_rate: 1, stats: stats({ median_cost_usd: '0.10' }) }),
          variant({ workflow_id: 'wf-steady', pass_rate: 0.5 }),
        ]}
        by={{ 'wf-lucky': { pass: 1, fail: 0, unscored: 7 }, 'wf-steady': { pass: 2, fail: 2 } }}
      />,
    )
    expect(document.querySelector('tr[data-best]')).toBeNull()
    expect(screen.getByText('1 judged')).toBeInTheDocument()
    expect(screen.getByText('4 judged')).toBeInTheDocument()
  })

  it('says judged counts are unavailable and crowns no variant when the run history is incomplete', () => {
    const vs = [variant({ workflow_id: 'wf-low', pass_rate: 0.25 }), variant({ workflow_id: 'wf-high', pass_rate: 0.9 })]
    render(<Compare variants={vs} by={null} />)
    expect(document.querySelector('tr[data-best]')).toBeNull()
    expect(screen.getAllByText('judged count unavailable')).toHaveLength(2)
    expect(screen.queryByText(/\d judged/)).toBeNull()
  })

  it('renders variants with no stats (an older API): figures say unavailable and sorting still works', async () => {
    render(
      <Compare
        variants={[withoutStats(variant({ workflow_id: 'wf-old' })), variant({ workflow_id: 'wf-new', stats: stats({ median_cost_usd: '0.20' }) })]}
      />,
    )
    const order = () => screen.getAllByRole('row').slice(1).map((r) => r.textContent?.match(/wf-[a-z]+/)?.[0])
    await userEvent.click(screen.getByRole('button', { name: /Median cost/ }))
    expect(order()).toEqual(['wf-new', 'wf-old'])
    const [, , oldRow] = screen.getAllByRole('row')
    expect(within(oldRow).getAllByText('stats unavailable')).toHaveLength(2)
  })

  it('sorts by a column on click, flipping on a second click, with a missing figure always last', async () => {
    render(
      <Compare
        variants={[
          variant({ workflow_id: 'wf-mid', stats: stats({ median_cost_usd: '0.50' }) }),
          variant({ workflow_id: 'wf-unknown', stats: stats({ median_cost_usd: null }) }),
          variant({ workflow_id: 'wf-cheap', stats: stats({ median_cost_usd: '0.10' }) }),
        ]}
      />,
    )
    const order = () => screen.getAllByRole('row').slice(1).map((r) => r.textContent?.match(/wf-[a-z]+/)?.[0])
    const header = screen.getByRole('button', { name: /Median cost/ })

    await userEvent.click(header)
    expect(order()).toEqual(['wf-cheap', 'wf-mid', 'wf-unknown'])
    expect(header.closest('th')).toHaveAttribute('aria-sort', 'ascending')
    await userEvent.click(header)
    expect(order()).toEqual(['wf-mid', 'wf-cheap', 'wf-unknown'])
  })

  it('scrolls inside its own container on a narrow screen instead of dropping columns', () => {
    render(<Compare variants={[variant()]} />)
    expect(screen.getByTestId('variants-scroll')).toHaveClass('overflow-x-auto')
    expect(screen.getByText('$0.41 med.').closest('td')).not.toHaveClass('hidden')
  })

  it('shows one row per variant with its workflow and observed models', () => {
    render(
      <Compare
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

  it('shows two versions of one workflow as two rows, each naming its version', () => {
    render(
      <Compare
        variants={[
          variant({ workflow_version: '1.4.0', pass_rate_display: '100% (1/1)' }),
          variant({ workflow_version: '2.0.0', pass_rate_display: '0% (0/1)' }),
        ]}
      />,
    )
    expect(screen.getAllByRole('row')).toHaveLength(3)
    expect(screen.getByText('@ 1.4.0', { exact: false })).toBeInTheDocument()
    expect(screen.getByText('@ 2.0.0', { exact: false })).toBeInTheDocument()
  })

  it('omits the version when the server recorded none', () => {
    render(<Compare variants={[variant({ workflow_version: null })]} />)
    expect(screen.queryByText('@', { exact: false })).toBeNull()
  })

  it('says there is nothing to compare when no variant has run', () => {
    render(<Compare variants={[]} />)
    expect(screen.getByText(/nothing to compare/)).toBeInTheDocument()
  })

  it('lets long workflow ids and model ids break instead of overflowing', () => {
    render(<Compare variants={[variant({ models: [LONG_MODEL] })]} />)
    expect(screen.getByText(LONG_MODEL).closest('td')).toHaveClass('break-all')
    expect(screen.getByRole('table')).toHaveClass('table-fixed')
  })
})

describe('EvalVariantsTable on a phone', () => {
  afterEach(() => vi.unstubAllGlobals())

  function phone() {
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: false,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    }))
  }

  it('shows one card per variant with every figure in view, no table to swipe', () => {
    phone()
    render(<Compare variants={[variant()]} />)
    expect(screen.queryByRole('table')).toBeNull()
    const [card] = within(screen.getByRole('list', { name: 'Variants' })).getAllByRole('listitem')
    for (const [label, value] of [
      ['Pass rate', '66.7% (2/3)'],
      ['Judged', '3 judged'],
      ['Median duration', '20m med.'],
      ['Median cost', '$0.41 med.'],
      ['Cost per PASS', '>=$0.62 (partial)'],
    ]) {
      expect(within(card).getByText(label).nextElementSibling).toHaveTextContent(value)
    }
    expect(within(card).getByText('wf-verifier')).toBeInTheDocument()
  })

  it('marks the best card the same way the table marks the best row', () => {
    phone()
    render(<Compare variants={[variant({ workflow_id: 'wf-low', pass_rate: 0.2 }), variant({ workflow_id: 'wf-high', pass_rate: 0.9 })]} />)
    const best = document.querySelectorAll('li[data-best]')
    expect(best).toHaveLength(1)
    expect(best[0]).toHaveTextContent('wf-high')
    expect(best[0]).toHaveTextContent('Best · 3 judged')
  })
})

describe('EvalVariantsStrip', () => {
  it('reads workflow and models to pass rate on one chip', () => {
    render(<EvalVariantsStrip variants={[variant()]} />)
    expect(screen.getByRole('listitem')).toHaveTextContent('wf-verifier @ 1.4.0 · claude-sonnet-5 → 66.7% (2/3)')
  })
})
