/**
 * The Phase Pipeline shows the cost text the API renders (#897), never its own,
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

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { PhaseTimeline } from '../PhaseTimeline'
import type { ExecutionDetailResponse } from '../../../types'
import type { components } from '../../../generated/api-types'
import { withPlanOfPhases } from '../../../test/phasePlanFixtures'
import {
  COST_COVERAGE_CASES,
  DISTINCT_EXECUTION_COST,
  SUB_CENT_CASE,
  executionCost,
  phaseCost,
} from '../../../test/costCoverageFixtures'

type Phase = ExecutionDetailResponse['phases'][number]

function phase(overrides: Partial<Phase> & { phase_id: string }): Phase {
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
    cost_usd: '0',
    cost_display: '$0.00',
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
    phase_progress: { completed: 0, skipped: 0, possible: 1, remaining_possible: 1, percent: 0, display: 'phase 1 of up to 1' },
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
    total_cost_usd: '0',
    total_cost_display: '$0.00',
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
      <PhaseTimeline execution={withPlanOfPhases(execution(phases, overrides))} now={Date.now()} />
    </MemoryRouter>,
  )
}

/** The header roll-up lives in the metrics strip above the phase cards. */
function headerStrip(): string {
  const strip = document.querySelector('.phase-pipeline-stats')
  return strip?.textContent ?? ''
}

describe('PhaseTimeline cost text', () => {
  // The API owns the wording (#897): every display string below is one the
  // client formatter cannot produce from the numbers beside it, so a surface
  // that formats the dollars itself again cannot pass.
  it.each([...COST_COVERAGE_CASES, SUB_CENT_CASE])('shows the execution total verbatim when $name', (c) => {
    renderTimeline([phase({ phase_id: 'implement' })], executionCost(c))
    expect(headerStrip()).toContain(c.shows)
  })

  it('follows the execution, not the phases, for the header total (#1048)', () => {
    // On the live path each phase is seeded 0 while the execution total is
    // real; a roll-up summed from the cards reports the cards, not the run.
    renderTimeline(
      [
        phase({ phase_id: 'plan', cost_usd: '1.5', cost_display: '$1.50' }),
        phase({ phase_id: 'build', cost_usd: '2.5', cost_display: '$2.50' }),
      ],
      { total_cost_usd: '6.25', total_cost_display: '$6.25' },
    )
    expect(headerStrip()).toContain('$6.25')
    expect(headerStrip()).not.toContain('$4.00')
  })

  it.each([...COST_COVERAGE_CASES, SUB_CENT_CASE])('shows each phase card cost verbatim when $name', (c) => {
    const { container } = renderTimeline(
      [phase({ phase_id: 'plan', ...phaseCost(c) })],
      DISTINCT_EXECUTION_COST,
    )
    // The header carries a different string, so the match can only be the card.
    expect(headerStrip()).not.toContain(c.shows)
    expect(container.textContent).toContain(c.shows)
  })
})

describe('PhaseTimeline per-model cost text (#897 slice O)', () => {
  // As the API serves them: `cost_by_model_display` is `format_cost` of each
  // value. A browser formatter would print $0.3057 and $0.0000 for these.
  const costByModel: components['schemas']['PhaseExecutionInfo']['cost_by_model'] = {
    'claude-opus-5-5': '0.30566780000000005',
    'claude-sonnet-5': '0.0000001',
    'gpt-6-sol': '0.1',
  }
  const costByModelDisplay: components['schemas']['PhaseExecutionInfo']['cost_by_model_display'] = {
    'claude-opus-5-5': '$0.31',
    'claude-sonnet-5': '<$0.01',
  }

  /** The cost text on the breakdown row whose label is `model`. */
  function rowCost(model: string): string {
    return screen.getByText(model).nextElementSibling?.textContent ?? ''
  }

  it('renders each model the API priced verbatim, and a dash where it sent none', () => {
    renderTimeline([
      phase({ phase_id: 'plan', cost_by_model: costByModel, cost_by_model_display: costByModelDisplay }),
    ])
    expect(rowCost('claude-opus-5-5')).toMatch(/^\$0\.31 · \d+%$/)
    expect(rowCost('claude-sonnet-5')).toMatch(/^<\$0\.01 · \d+%$/)
    // Missing from the display map: never a number the browser formatted.
    expect(rowCost('gpt-6-sol')).toMatch(/^— · \d+%$/)
    expect(document.body.textContent).not.toMatch(/\$0\.\d{4}/)
  })
})

describe('PhaseTimeline with an unknown phase duration', () => {
  // `duration_seconds` is `float | None` on the API and resolve_duration_seconds
  // returns None for "unknown, never 0.0". The hand-written dashboard type used
  // to declare it `number`, so `.toFixed(1)` type-checked and threw at runtime,
  // taking the whole page down with it.
  it('renders a phase whose duration is unknown without crashing', () => {
    const { container } = renderTimeline([
      phase({ phase_id: 'plan', duration_seconds: null }),
    ])
    expect(container.textContent).toContain('Phase')
  })

  it('shows an unknown duration as unknown, not as a measured 0.0', () => {
    const { container } = renderTimeline([
      phase({ phase_id: 'plan', duration_seconds: null }),
    ])
    // The backend deliberately distinguishes "no reading" from "took no time",
    // so the card must not launder the first into the second.
    expect(container.textContent).not.toContain('0.0s')
    expect(container.textContent).toContain('\u2014')
  })

  it('keeps unknown phases out of the header total instead of counting them as 0', () => {
    renderTimeline([
      phase({ phase_id: 'plan', duration_seconds: 60 }),
      phase({ phase_id: 'build', duration_seconds: null }),
    ])
    // 60.0s is a real reading of one phase, not of the execution: say how many
    // phases it does not cover rather than implying it covers them all.
    expect(headerStrip()).toContain('60.0s')
    expect(headerStrip()).toContain('+1 unknown')
  })

  it('reports the whole header duration as unknown when no phase has one', () => {
    renderTimeline([
      phase({ phase_id: 'plan', duration_seconds: null }),
      phase({ phase_id: 'build', duration_seconds: null }),
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
          phase_id: 'implement',
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
        phase({ phase_id: 'plan' }),
        phase({
          phase_id: 'implement',
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
          phase_id: 'implement',
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
    const { container } = renderTimeline([phase({ phase_id: 'plan' })])

    expect(container.textContent).toContain('300')
    expect(container.textContent).not.toContain('so far')
  })

  it('qualifies only the running phase when phases are mixed', () => {
    const { container } = renderTimeline([
      phase({ phase_id: 'plan' }),
      phase({
        phase_id: 'implement',
        status: 'running',
        input_tokens: 0,
        output_tokens: 0,
      }),
      phase({ phase_id: 'review', status: 'pending', input_tokens: 0, output_tokens: 0 }),
    ])

    // A pending phase really has used no tokens, so its 0 is a reading and
    // stays unqualified; only the running one is still being counted.
    expect(container.textContent?.match(/so far/g)).toHaveLength(1)
  })
})

describe('a failed phase card says why that phase failed (#1592)', () => {
  it('shows the phase’s own classification and error text, not the run’s', () => {
    const { getByTestId } = renderTimeline(
      [
        phase({
          phase_id: 'verify',
          status: 'failed',
          error_message: 'Agent failed: codex reported: Selected model is at capacity.',
          failure_classification: 'platform',
          reported_failure_reason: 'platform',
        }),
      ],
      // The run says something different on purpose: a card that borrowed the
      // execution's classification or text would render these instead.
      { status: 'failed', failure_classification: 'correct_refusal', error_message: 'run text' },
    )

    const failure = getByTestId('phase-failure')
    expect(failure.textContent).toContain('platform')
    expect(failure.textContent).toContain('Selected model is at capacity.')
    expect(failure.textContent).toContain('The agent reported: platform')
    expect(failure.textContent).not.toContain('correct_refusal')
    expect(failure.textContent).not.toContain('run text')
    expect(failure.closest('[class*="red-"]')).not.toBeNull()
  })

  it('says nothing about failure on a phase that did not fail', () => {
    const { queryByTestId } = renderTimeline([phase({ phase_id: 'plan' })])
    expect(queryByTestId('phase-failure')).toBeNull()
  })
})
