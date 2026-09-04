/**
 * The Phase Pipeline header must not report unpriced work as $0.0000 (#890),
 * and must not report a live run's tokens as 0 (#1048).
 *
 * The per-phase cards were fixed first; the header roll-up is a SECOND consumer
 * of the same data and kept deriving its own answer. These cases pin the
 * aggregate specifically, because a suite that only checks the cards stays
 * green while the total above them lies.
 *
 * Every token fixture below sets `total_tokens` to a figure the per-phase
 * fields cannot produce, so the assertions fail against a total summed from
 * those fields. A self-consistent payload would pass either way and prove
 * nothing.
 */

import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { PhaseTimeline } from '../PhaseTimeline'
import type { ExecutionDetailResponse } from '../../../types'

type Phase = ExecutionDetailResponse['phases'][number]

function phase(overrides: Partial<Phase> & { workflow_phase_id: string }): Phase {
  return {
    name: 'Phase',
    status: 'completed',
    session_id: null,
    agent_session_id: null,
    artifact_id: null,
    input_tokens: 100,
    output_tokens: 200,
    cache_creation_tokens: 0,
    cache_read_tokens: 0,
    duration_seconds: 1,
    cost_usd: 0,
    unpriced_observation_count: 0,
    started_at: null,
    completed_at: null,
    model: null,
    cost_by_model: {},
    ...overrides,
  } as Phase
}

/**
 * An execution wrapping the given phases.
 *
 * The execution-level token fields default to 0 so a test that cares about
 * them has to say so; `renderTimeline` is otherwise only exercising the cost
 * and duration roll-ups, which are Lane 2 and live per phase already.
 */
function execution(
  phases: Phase[],
  overrides: Partial<ExecutionDetailResponse> = {},
): ExecutionDetailResponse {
  return {
    workflow_execution_id: 'exec-1',
    workflow_id: 'wf-1',
    workflow_name: 'Run',
    status: 'running',
    started_at: null,
    completed_at: null,
    phases,
    total_input_tokens: 0,
    total_output_tokens: 0,
    total_cache_creation_tokens: 0,
    total_cache_read_tokens: 0,
    total_tokens: 0,
    total_cost_usd: 0,
    unpriced_observation_count: 0,
    artifact_ids: [],
    error_message: null,
    repos: [],
    total_duration_seconds: 0,
    ...overrides,
  } as unknown as ExecutionDetailResponse
}

function renderTimeline(phases: Phase[], overrides: Partial<ExecutionDetailResponse> = {}) {
  return render(
    <MemoryRouter>
      <PhaseTimeline execution={execution(phases, overrides)} now={Date.now()} />
    </MemoryRouter>,
  )
}

/** The header roll-up lives in the metrics strip above the phase cards. */
function headerStrip(): string {
  const strip = document.querySelector('.flex.items-center.gap-4')
  return strip?.textContent ?? ''
}

describe('PhaseTimeline cost roll-up', () => {
  // Every fixture sets the execution-level cost to a figure the phases cannot
  // produce. On the live path the domain hands back an empty cost_by_phase map,
  // so each phase is seeded cost_usd=0 while the execution total is real - a
  // roll-up summed from the cards prints "$0.000000" under a $0.42 headline.
  it('reports the execution total, not the sum of the phase cards', () => {
    // The exact shape from the report: one phase, seeded 0, live total $0.42.
    renderTimeline([phase({ workflow_phase_id: 'implement', cost_usd: 0 })], {
      total_cost_usd: 0.42,
    })
    expect(headerStrip()).toContain('$0.42')
    expect(headerStrip()).not.toContain('$0.000000')
  })

  it('follows the execution even when the phases carry costs of their own', () => {
    // Phases sum to $4.00; the execution says $6.25. Only one of those is the
    // figure the Total Cost card shows, and the header must agree with it.
    renderTimeline(
      [
        phase({ workflow_phase_id: 'plan', cost_usd: 1.5 }),
        phase({ workflow_phase_id: 'build', cost_usd: 2.5 }),
      ],
      { total_cost_usd: 6.25 },
    )
    expect(headerStrip()).toContain('$6.25')
    expect(headerStrip()).not.toContain('$4.00')
    expect(headerStrip()).not.toContain('unpriced')
  })

  it('says unpriced, not $0.000000, when nothing could be priced', () => {
    // The #890 coverage signal lives at execution level too: unpriced_by_phase
    // is empty on the live path, so a count summed from the phases reads 0 and
    // the zero cost renders as a confident figure.
    renderTimeline([phase({ workflow_phase_id: 'plan', unpriced_observation_count: 0 })], {
      total_cost_usd: 0,
      unpriced_observation_count: 11,
    })
    expect(headerStrip()).toContain('unpriced')
    expect(headerStrip()).not.toContain('$0.000000')
  })

  it('marks a mixed total as a lower bound rather than a complete figure', () => {
    renderTimeline([phase({ workflow_phase_id: 'plan', unpriced_observation_count: 0 })], {
      total_cost_usd: 3,
      unpriced_observation_count: 9,
    })
    const text = headerStrip()
    expect(text).toContain('(partial)')
    expect(text).toContain('$3.00')
  })

  it('treats a genuinely free priced execution as $0, not unpriced', () => {
    renderTimeline([phase({ workflow_phase_id: 'plan' })], {
      total_cost_usd: 0,
      unpriced_observation_count: 0,
    })
    expect(headerStrip()).not.toContain('unpriced')
  })
})

describe('PhaseTimeline with an unknown phase duration', () => {
  // `duration_seconds` is `float | None` on the API and resolve_duration_seconds
  // returns None for "unknown, never 0.0". The hand-written dashboard type used
  // to declare it `number`, so `.toFixed(1)` type-checked and threw at runtime,
  // taking the whole page down with it.
  it('renders a phase whose duration is unknown without crashing', () => {
    const { container } = renderTimeline([
      phase({ workflow_phase_id: 'plan', duration_seconds: null }),
    ])
    expect(container.textContent).toContain('Phase')
  })

  it('shows an unknown duration as unknown, not as a measured 0.0', () => {
    const { container } = renderTimeline([
      phase({ workflow_phase_id: 'plan', duration_seconds: null }),
    ])
    // The backend deliberately distinguishes "no reading" from "took no time",
    // so the card must not launder the first into the second.
    expect(container.textContent).not.toContain('0.0s')
    expect(container.textContent).toContain('\u2014')
  })

  it('keeps unknown phases out of the header total instead of counting them as 0', () => {
    renderTimeline([
      phase({ workflow_phase_id: 'plan', duration_seconds: 60 }),
      phase({ workflow_phase_id: 'build', duration_seconds: null }),
    ])
    // 60.0s is a real reading of one phase, not of the execution: say how many
    // phases it does not cover rather than implying it covers them all.
    expect(headerStrip()).toContain('60.0s')
    expect(headerStrip()).toContain('+1 unknown')
  })

  it('reports the whole header duration as unknown when no phase has one', () => {
    renderTimeline([
      phase({ workflow_phase_id: 'plan', duration_seconds: null }),
      phase({ workflow_phase_id: 'build', duration_seconds: null }),
    ])
    expect(headerStrip()).not.toContain('0.0s')
  })
})

describe('PhaseTimeline token roll-up while a phase is running', () => {
  it('reports the live execution total, not the frozen sum of the phases', () => {
    // The one phase is mid-run, so Lane 1 has written nothing to it. Summing
    // the phases renders "0 tokens" under a headline reading 1,234,567.
    renderTimeline(
      [
        phase({
          workflow_phase_id: 'implement',
          status: 'running',
          input_tokens: 0,
          output_tokens: 0,
        }),
      ],
      { total_tokens: 1_234_567 },
    )

    expect(headerStrip()).toContain('1.2M tokens')
    expect(headerStrip()).not.toContain('0 tokens')
  })

  it('reports the live total when only some phases have landed', () => {
    // 300 attributed to the finished phase, 1000 actually counted: the roll-up
    // must follow the execution, not the 300 it can see beneath it.
    renderTimeline(
      [
        phase({ workflow_phase_id: 'plan' }),
        phase({
          workflow_phase_id: 'implement',
          status: 'running',
          input_tokens: 0,
          output_tokens: 0,
        }),
      ],
      { total_input_tokens: 100, total_output_tokens: 200, total_tokens: 1000 },
    )

    expect(headerStrip()).toContain('1.0K tokens')
    expect(headerStrip()).not.toContain('300 tokens')
  })
})

describe('PhaseTimeline per-phase token figures', () => {
  it('does not present a running phase’s frozen 0 as a finished count', () => {
    const { container } = renderTimeline(
      [
        phase({
          workflow_phase_id: 'implement',
          status: 'running',
          input_tokens: 0,
          output_tokens: 0,
        }),
      ],
      { total_tokens: 1_234_567 },
    )

    expect(container.textContent).toContain('0 so far')
  })

  it('leaves a settled phase’s count unqualified', () => {
    // 'so far' on every card would be as uninformative as never showing it:
    // this pins the label to the phase's status, not to the component.
    const { container } = renderTimeline([phase({ workflow_phase_id: 'plan' })])

    expect(container.textContent).toContain('300')
    expect(container.textContent).not.toContain('so far')
  })

  it('qualifies only the running phase when phases are mixed', () => {
    const { container } = renderTimeline([
      phase({ workflow_phase_id: 'plan' }),
      phase({
        workflow_phase_id: 'implement',
        status: 'running',
        input_tokens: 0,
        output_tokens: 0,
      }),
      phase({ workflow_phase_id: 'review', status: 'pending', input_tokens: 0, output_tokens: 0 }),
    ])

    // A pending phase really has used no tokens, so its 0 is a reading and
    // stays unqualified; only the running one is still being counted.
    expect(container.textContent?.match(/so far/g)).toHaveLength(1)
  })
})
