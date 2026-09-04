/**
 * The execution page must show the LIVE token total while a phase is running.
 *
 * `total_tokens` is the only token field the API keeps live. The four
 * component fields are Lane 1 phase sums and a running phase leaves them at 0
 * until it completes, so every figure re-derived from them reads 0 for the
 * whole of a live run — which is what #1048 reported and what the first cut of
 * #1071 left in place: polling delivered a fresh payload that the page then
 * rendered as "0".
 *
 * Every fixture below sets `total_tokens` to a value the component fields
 * cannot produce, so the assertions fail against a total summed from the parts.
 * A self-consistent payload would pass either way and prove nothing.
 */

import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ExecutionDetailResponse } from '../../../types'

const useExecutionData = vi.fn()

vi.mock('../../../hooks', () => ({
  useExecutionData: (executionId: string | undefined) => useExecutionData(executionId),
}))

// Imported after the mock is registered so the page picks up the stub.
const { ExecutionDetail } = await import('../ExecutionDetail')

/** A run whose only phase is still going: live total, no attributed parts. */
function midPhaseExecution(
  overrides: Partial<ExecutionDetailResponse> = {},
): ExecutionDetailResponse {
  return {
    workflow_execution_id: 'exec-1048',
    workflow_id: 'wf-1',
    workflow_name: 'Live run',
    status: 'running',
    started_at: new Date().toISOString(),
    completed_at: null,
    phases: [
      {
        workflow_phase_id: 'phase-1',
        name: 'implement',
        status: 'running',
        session_id: 'sess-1',
        agent_session_id: null,
        artifact_id: null,
        input_tokens: 0,
        output_tokens: 0,
        cache_creation_tokens: 0,
        cache_read_tokens: 0,
        duration_seconds: 0,
        cost_usd: 0,
        unpriced_observation_count: 0,
        started_at: new Date().toISOString(),
        completed_at: null,
        model: null,
        cost_by_model: {},
      },
    ],
    total_input_tokens: 0,
    total_output_tokens: 0,
    total_cache_creation_tokens: 0,
    total_cache_read_tokens: 0,
    total_tokens: 1_234_567,
    total_cost_usd: 4.25,
    unpriced_observation_count: 0,
    artifact_ids: [],
    error_message: null,
    repos: [],
    total_duration_seconds: 0,
    ...overrides,
  } as unknown as ExecutionDetailResponse
}

function renderExecution(
  execution: ExecutionDetailResponse | null,
  hookOverrides: { error?: string | null; loading?: boolean; isConnected?: boolean } = {},
) {
  useExecutionData.mockReturnValue({
    execution,
    artifactDetails: {},
    loading: false,
    error: null,
    isConnected: true,
    now: Date.now(),
    refreshExecution: vi.fn(),
    ...hookOverrides,
  })
  return render(
    <MemoryRouter initialEntries={['/executions/exec-1048']}>
      <ExecutionDetail />
    </MemoryRouter>,
  )
}

/**
 * The headline figure and its sublabel, read separately.
 *
 * MetricCard renders title, value and subtitle as consecutive paragraphs, so
 * the value can be asserted exactly. Matching the card's whole text would let
 * a "0" in the sublabel satisfy an assertion about the headline.
 */
function metricCard(title: string): { value: string; subtitle: string } {
  const titleEl = screen.getByText(title)
  const valueEl = titleEl.nextElementSibling
  return {
    value: valueEl?.textContent ?? '',
    subtitle: valueEl?.nextElementSibling?.textContent ?? '',
  }
}

beforeEach(() => {
  useExecutionData.mockReset()
})

describe('ExecutionDetail token totals while a phase is running', () => {
  it('renders the live total, not the frozen sum of the per-phase parts', () => {
    renderExecution(midPhaseExecution())

    // 1,234,567 appears in no component field; only total_tokens carries it.
    // Summing the parts renders "0".
    expect(metricCard('Total Tokens').value).toBe('1,234,567')
  })

  it('keeps the Token Usage card on screen instead of hiding a live total', () => {
    const { container } = renderExecution(midPhaseExecution())

    // The card early-returns null when its total is 0, so a total summed from
    // the parts deletes the entire breakdown for the whole of a live run.
    const section = container.querySelector('#token-breakdown')
    expect(section).not.toBeNull()
    const card = within(section as HTMLElement)
    expect(card.getByText('Token Usage')).toBeTruthy()
    expect(card.getByText('In Progress')).toBeTruthy()
    expect(card.getByText('1.2M')).toBeTruthy()
  })

  it('accounts for the unattributed remainder so the parts reach the headline', () => {
    // One phase has landed (300 attributed) while the next runs on: the live
    // total is 700 ahead of the parts.
    renderExecution(
      midPhaseExecution({
        total_input_tokens: 100,
        total_output_tokens: 200,
        total_tokens: 1000,
      }),
    )

    const card = metricCard('Total Tokens')
    expect(card.value).toBe('1,000')
    // The sublabel must not present 100/200 as though it were the whole total.
    expect(card.subtitle).toBe('In: 100 / Out: 200 / 700 in progress')
  })

  it('does not contradict its own headline in the Phase Pipeline below it', () => {
    // The defect this case exists for: the headline read the live total while
    // the roll-up one card down re-derived its own from the frozen per-phase
    // fields, so the page showed 1,234,567 and "0 tokens" at the same time.
    const { container } = renderExecution(midPhaseExecution())

    expect(metricCard('Total Tokens').value).toBe('1,234,567')

    const timeline = container.querySelector('#phase-timeline')
    expect(timeline).not.toBeNull()
    const rollUp = within(timeline as HTMLElement).getByText(/tokens$/)
    expect(rollUp.textContent).toBe('1.2M tokens')
  })

  it('shows no in-progress remainder once the parts account for the total', () => {
    renderExecution(
      midPhaseExecution({
        status: 'completed',
        total_input_tokens: 100,
        total_output_tokens: 200,
        total_cache_creation_tokens: 300,
        total_cache_read_tokens: 400,
        total_tokens: 1000,
      }),
    )

    const card = metricCard('Total Tokens')
    expect(card.value).toBe('1,000')
    expect(card.subtitle).toBe('In: 800 / Out: 200')
    expect(screen.queryByText('In Progress')).toBeNull()
  })
})

describe('ExecutionDetail through a recoverable poll failure (#1048)', () => {
  // The page polls every 3s for the life of a run. The render guard was
  // `if (error || !execution)`, so the first transient 502 replaced a live page
  // with "Execution not found" — permanently, because the hook never cleared
  // `error` on a later success. A failed refresh means the numbers stopped
  // advancing, not that the execution vanished.
  it('keeps the metrics on screen when the last refresh failed', () => {
    renderExecution(midPhaseExecution(), { error: '502 Bad Gateway' })

    expect(screen.queryByText('Execution not found')).toBeNull()
    expect(metricCard('Total Tokens').value).toBe('1,234,567')
    expect(metricCard('Total Cost').value).toBe('$4.25')
  })

  it('says the page has stopped updating instead of failing silently', () => {
    renderExecution(midPhaseExecution(), { error: '502 Bad Gateway' })

    // Non-blocking, and it names the reason: a page that quietly froze would
    // be worse than the empty state it replaced.
    const indicator = screen.getByText(/Not updating/)
    expect(indicator).toBeTruthy()
    expect(indicator.closest('[title]')?.getAttribute('title')).toBe('502 Bad Gateway')
    expect(screen.queryByText('Live')).toBeNull()
  })

  it('still shows the empty state when there is genuinely no execution', () => {
    // The guard must narrow to "no data", not disappear: an unknown id has
    // nothing to render and must not fall through to the page body.
    renderExecution(null, { error: 'Not Found' })

    expect(screen.getByText('Execution not found')).toBeTruthy()
  })

  it('reports Live again once a later poll succeeds', () => {
    renderExecution(midPhaseExecution(), { error: null })

    expect(screen.getByText('Live')).toBeTruthy()
    expect(screen.queryByText(/Not updating/)).toBeNull()
  })
})

describe('ExecutionDetail cost-by-model against the execution total (#1048)', () => {
  it('does not present a partial per-model breakdown as the execution total', () => {
    // One phase has landed and carries a $1.00 model row; the execution has
    // actually cost $4.25 so far. The card used to sum its own rows and label
    // that "total", contradicting the Total Cost card directly above it.
    const execution = midPhaseExecution({
      phases: [
        {
          ...midPhaseExecution().phases[0],
          status: 'completed',
          cost_by_model: { 'claude-sonnet-5-20250101': '1.00' },
        },
      ],
    })
    const { container } = renderExecution(execution)

    const section = container.querySelector('#cost-by-model')
    expect(section).not.toBeNull()
    const card = within(section as HTMLElement)

    expect(card.getByText('$4.25')).toBeTruthy()
    // The $3.25 the breakdown cannot attribute is shown, not dropped: the
    // parts have to add up to the headline.
    expect(card.getByText('not yet attributed')).toBeTruthy()
    expect(card.getByText('$3.25')).toBeTruthy()
  })
})
