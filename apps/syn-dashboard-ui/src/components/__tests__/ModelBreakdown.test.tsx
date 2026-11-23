/**
 * Cost by Model shows observed ids verbatim and the unattributed bucket as
 * "unknown model" (ADR-067 D9), never the raw key and never a shortened id.
 *
 * Every dollar figure is the API's text (#897). The verbatim tests carry
 * sentinel strings (`API-*`) no formatter produces, so a figure re-formatted in
 * the browser cannot pass. Every other fixture carries what the API's
 * `format_cost` sends for the amounts beside it.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { UNATTRIBUTED_MODEL_KEY, UNATTRIBUTED_MODEL_LABEL } from '../../constants/models'
import type { components } from '../../generated/api-types'
import { ModelBreakdown } from '../ModelBreakdown'

type ExecutionCostByModel = Pick<
  components['schemas']['ExecutionDetailResponse'],
  'cost_by_model' | 'total_cost_usd' | 'total_cost_display' | 'cost_by_model_display' | 'unattributed_cost_display'
>
type SessionCostByModel = Pick<
  components['schemas']['SessionResponse'],
  'cost_by_model' | 'total_cost_usd' | 'total_cost_display' | 'cost_by_model_display' | 'unattributed_cost_display'
>

function renderScope(scope: ExecutionCostByModel | SessionCostByModel) {
  return render(
    <ModelBreakdown
      costByModel={scope.cost_by_model ?? {}}
      totalCost={scope.total_cost_usd}
      totalCostDisplay={scope.total_cost_display}
      costByModelDisplay={scope.cost_by_model_display}
      unattributedCostDisplay={scope.unattributed_cost_display}
    />,
  )
}

/** The text in the same row as `label`. */
function rowText(label: string): string {
  return screen.getByText(label).closest('.space-y-1')?.textContent ?? ''
}

// Real amounts from GET /executions/exec-105b88d56234 (beta.7), phase 2 still
// running: its map is empty, the total already counts it.
const MID_RUN_EXECUTION: ExecutionCostByModel = {
  cost_by_model: { 'claude-opus-5-5': '0.30566780000000005' },
  total_cost_usd: '0.43809100000000005',
  total_cost_display: 'API-TOTAL',
  cost_by_model_display: { 'claude-opus-5-5': 'API-OPUS' },
  unattributed_cost_display: 'API-REMAINDER',
}

describe('ModelBreakdown', () => {
  it('renders the total, each row and the remainder verbatim from the API', () => {
    renderScope(MID_RUN_EXECUTION)
    expect(screen.getByText('API-TOTAL')).toBeTruthy()
    expect(rowText('claude-opus-5-5')).toContain('API-OPUS')
    expect(rowText('not yet attributed')).toContain('API-REMAINDER')
    expect(screen.queryByText(/\$/)).toBeNull()
  })

  it('keeps the bar widths in exact decimal', () => {
    renderScope(MID_RUN_EXECUTION)
    // 0.30566780000000005 / 0.43809100000000005 = 69.77%; the remainder is the rest.
    expect(rowText('claude-opus-5-5')).toContain('69.8%')
    expect(rowText('not yet attributed')).toContain('30.2%')
  })

  it('draws no remainder row when the API sends none', () => {
    // The rows account for the total exactly; float subtraction leaves ~1e-17.
    renderScope({
      cost_by_model: { 'claude-opus-5-5': '0.30566780000000005', 'gpt-6-sol': '0.1324232' },
      total_cost_usd: '0.43809100000000005',
      total_cost_display: '$0.44',
      cost_by_model_display: { 'claude-opus-5-5': '$0.31', 'gpt-6-sol': '$0.13' },
      unattributed_cost_display: null,
    })
    expect(rowText('claude-opus-5-5')).toContain('$0.31')
    expect(rowText('gpt-6-sol')).toContain('$0.13')
    expect(screen.queryByText('not yet attributed')).toBeNull()
  })

  it('shows an em dash for a row the API sent no text for, never a client figure', () => {
    renderScope({
      cost_by_model: { 'claude-opus-5-5': '0.3', 'gpt-6-sol': '0.1' },
      total_cost_usd: '0.4',
      total_cost_display: '$0.40',
      // Deliberately missing gpt-6-sol: the defensive fallback, not a producer shape.
      cost_by_model_display: { 'claude-opus-5-5': '$0.30' },
      unattributed_cost_display: null,
    })
    const row = rowText('gpt-6-sol')
    expect(row).toContain('—')
    expect(row).not.toContain('$')
  })

  it('renders a session scope from its own display fields', () => {
    renderScope({
      cost_by_model: { 'claude-sonnet-5-5': '0.004' },
      total_cost_usd: '0.004',
      total_cost_display: '<$0.01',
      cost_by_model_display: { 'claude-sonnet-5-5': '<$0.01' },
      unattributed_cost_display: null,
    } satisfies SessionCostByModel)
    expect(rowText('claude-sonnet-5-5')).toContain('<$0.01')
    expect(screen.getAllByText('<$0.01')).toHaveLength(2)
  })

  it('renders the unattributed key as "unknown model"', () => {
    renderScope({
      cost_by_model: { [UNATTRIBUTED_MODEL_KEY]: '0.2', 'claude-opus-5-5': '0.3' },
      total_cost_usd: '0.5',
      total_cost_display: '$0.50',
      cost_by_model_display: { [UNATTRIBUTED_MODEL_KEY]: '$0.20', 'claude-opus-5-5': '$0.30' },
      unattributed_cost_display: null,
    })
    expect(screen.getByText(UNATTRIBUTED_MODEL_LABEL)).toBeTruthy()
    expect(screen.queryByText(UNATTRIBUTED_MODEL_KEY)).toBeNull()
  })

  it('renders the full observed id, not a shortened one', () => {
    renderScope({
      cost_by_model: { 'claude-sonnet-5-20260101': '0.3' },
      total_cost_usd: '0.3',
      total_cost_display: '$0.30',
      cost_by_model_display: { 'claude-sonnet-5-20260101': '$0.30' },
      unattributed_cost_display: null,
    })
    expect(screen.getByText('claude-sonnet-5-20260101')).toBeTruthy()
    expect(screen.queryByText('sonnet-5')).toBeNull()
  })

  it('lists a model that ran unpriced with the backend label, never as $0 (#1743)', () => {
    render(
      <ModelBreakdown
        costByModel={{ 'gpt-5.6-sol': '0.19' }}
        totalCost="0.19"
        totalCostDisplay=">=$0.19 (partial)"
        costByModelDisplay={{ 'gpt-5.6-sol': '$0.19' }}
        unattributedCostDisplay={null}
        unpricedModels={['acme-reasoner-7b']}
        unpricedLabel="unpriced"
      />,
    )
    const row = screen.getByText('acme-reasoner-7b').parentElement
    expect(row?.textContent).toContain('unpriced')
    expect(row?.textContent).not.toContain('$')
  })

  it('renders when the only models it has are unpriced ones (#1743)', () => {
    render(
      <ModelBreakdown
        costByModel={{}}
        totalCost="0"
        totalCostDisplay="unpriced"
        costByModelDisplay={{}}
        unattributedCostDisplay={null}
        unpricedModels={['acme-reasoner-7b']}
        unpricedLabel="unpriced"
      />,
    )
    expect(screen.getByText('acme-reasoner-7b')).toBeTruthy()
  })
})
