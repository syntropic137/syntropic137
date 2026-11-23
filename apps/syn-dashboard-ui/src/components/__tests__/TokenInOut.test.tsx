/**
 * Cache writes are billed input-side and belong under In, not Out.
 *
 * Every card that splits tokens In/Out must agree with the execution header,
 * whose "In" counts fresh + cache write + cache read. The phase cards put
 * Cache write under Out, so for exec-105b88d56234 (beta.7) the header read
 * In: 351,251 while the plan card's In read 66,405 and its Out 34,975. Counts
 * below are that run.
 */

import { render, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { ExecutionDetailResponse } from '../../types'
import { PhaseTimeline } from '../../pages/ExecutionDetail/PhaseTimeline'
import { TokenInOut } from '../TokenInOut'
import { withPlanOfPhases } from '../../test/phasePlanFixtures'

// Plan phase of exec-105b88d56234.
const PLAN = { fresh: 6, cacheWrite: 33928, cacheRead: 66399, output: 1047 }

function segment(container: HTMLElement, name: 'in' | 'out'): HTMLElement {
  const el = container.querySelector<HTMLElement>(`[data-testid="token-segment-${name}"]`)
  if (!el) throw new Error(`no ${name} segment`)
  return el
}

function segmentTotal(container: HTMLElement, name: 'in' | 'out'): string {
  return within(segment(container, name)).getByTestId('token-segment-total').textContent ?? ''
}

describe('TokenInOut', () => {
  it('counts fresh, cache write and cache read as In, and only output as Out', () => {
    const { container } = render(<TokenInOut variant="compact" {...PLAN} />)
    expect(segmentTotal(container, 'in')).toBe((100333).toLocaleString())
    expect(segmentTotal(container, 'out')).toBe((1047).toLocaleString())
    expect(within(segment(container, 'in')).getByText('Cache write')).toBeTruthy()
    expect(within(segment(container, 'out')).queryByText('Cache write')).toBeNull()
  })
})

describe('every In/Out card agrees with the execution header', () => {
  it('phase timeline card', () => {
    const phase = {
      phase_id: 'plan',
      name: 'Plan (claude)',
      status: 'completed',
      session_id: null,
      agent_session_id: null,
      artifact_id: null,
      input_tokens: PLAN.fresh,
      output_tokens: PLAN.output,
      cache_creation_tokens: PLAN.cacheWrite,
      cache_read_tokens: PLAN.cacheRead,
      duration_seconds: 26.645056,
      cost_usd: 0.30566780000000005,
      unpriced_observation_count: 0,
      started_at: null,
      completed_at: null,
      model: 'claude-opus-5-5',
      requested_model: 'opus',
      model_display: 'claude-opus-5-5',
      cost_by_model: { 'claude-opus-5-5': '0.30566780000000005' },
    } as ExecutionDetailResponse['phases'][number]
    const execution = {
      workflow_execution_id: 'exec-105b88d56234',
      phase_progress: { completed: 0, skipped: 0, possible: 1, remaining_possible: 1, percent: 0, display: 'phase 1 of up to 1' },
      workflow_id: 'multi-agent-programmatic',
      workflow_name: 'Multi-agent',
      status: 'completed',
      phases: [phase],
      total_tokens: 101380,
      total_cost_usd: 0.30566780000000005,
      unpriced_observation_count: 0,
    } as unknown as ExecutionDetailResponse
    const { container } = render(
      <MemoryRouter>
        <PhaseTimeline execution={withPlanOfPhases(execution)} now={Date.now()} />
      </MemoryRouter>,
    )
    expect(segmentTotal(container, 'in')).toBe((100333).toLocaleString())
    expect(within(segment(container, 'in')).getByText('Cache write')).toBeTruthy()
    expect(segmentTotal(container, 'out')).toBe((1047).toLocaleString())
  })
})
