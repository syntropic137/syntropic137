/**
 * Cache writes are billed input-side and belong under In, not Out.
 *
 * Every card that splits tokens In/Out must agree with the execution header,
 * whose "In" counts fresh + cache write + cache read. The phase cards, the
 * execution cost summary and the session cost card all put Cache write under
 * Out, so for exec-105b88d56234 (beta.7) the header read In: 351,251 while the
 * plan card's In read 66,405 and its Out 34,975. Counts below are that run.
 */

import { render, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { ExecutionCost, ExecutionDetailResponse, SessionCost } from '../../types'
import { PhaseTimeline } from '../../pages/ExecutionDetail/PhaseTimeline'
import { ExecutionCostSummary } from '../ExecutionCostSummary'
import { SessionCostCard } from '../SessionCostCard'
import { TokenInOut } from '../TokenInOut'

// Plan phase of exec-105b88d56234.
const PLAN = { fresh: 6, cacheWrite: 33928, cacheRead: 66399, output: 1047 }
// Whole execution: header "In: 351,251 / Out: 5,163".
const EXEC = { input: 22828, cacheWrite: 33928, cacheRead: 294495, output: 5163 }

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
      workflow_phase_id: 'plan',
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
        <PhaseTimeline execution={execution} now={Date.now()} />
      </MemoryRouter>,
    )
    expect(segmentTotal(container, 'in')).toBe((100333).toLocaleString())
    expect(within(segment(container, 'in')).getByText('Cache write')).toBeTruthy()
    expect(segmentTotal(container, 'out')).toBe((1047).toLocaleString())
  })

  it('execution cost summary', () => {
    const cost = {
      execution_id: 'exec-105b88d56234',
      workflow_id: 'multi-agent-programmatic',
      session_count: 2,
      session_ids: null,
      total_cost_usd: 0.438091,
      token_cost_usd: 0.438091,
      compute_cost_usd: 0,
      input_tokens: EXEC.input,
      output_tokens: EXEC.output,
      total_tokens: 356414,
      cache_creation_tokens: EXEC.cacheWrite,
      cache_read_tokens: EXEC.cacheRead,
      tool_calls: 0,
      turns: 0,
      duration_ms: 0,
      cost_by_phase: {},
      unpriced_by_phase: {},
      cost_by_model: {},
      cost_by_tool: {},
      is_complete: true,
      unpriced_observation_count: 0,
      started_at: null,
      completed_at: null,
    } satisfies ExecutionCost
    const { container } = render(<ExecutionCostSummary cost={cost} />)
    // 351,251 abbreviated, exactly as the header's figure would be.
    expect(segmentTotal(container, 'in')).toBe('351.3K')
    expect(within(segment(container, 'in')).getByText('Cache write')).toBeTruthy()
    expect(segmentTotal(container, 'out')).toBe('5.2K')
  })

  it('session cost card', () => {
    const cost = {
      session_id: '036cd2ca-dc4a-4b71-9eee-6d5d3b4cc2b0',
      execution_id: 'exec-105b88d56234',
      workflow_id: 'multi-agent-programmatic',
      phase_id: 'plan',
      workspace_id: null,
      total_cost_usd: 0.3056678,
      token_cost_usd: 0.3056678,
      compute_cost_usd: 0,
      input_tokens: PLAN.fresh,
      output_tokens: PLAN.output,
      total_tokens: 101380,
      cache_creation_tokens: PLAN.cacheWrite,
      cache_read_tokens: PLAN.cacheRead,
      tool_calls: 0,
      turns: 0,
      duration_ms: 0,
      cost_by_model: {},
      cost_by_tool: {},
      tokens_by_tool: {},
      cost_by_tool_tokens: {},
      is_finalized: true,
      unpriced_observation_count: 0,
      started_at: null,
      completed_at: null,
    } satisfies SessionCost
    const { container } = render(<SessionCostCard cost={cost} />)
    expect(segmentTotal(container, 'in')).toBe('100.3K')
    expect(within(segment(container, 'in')).getByText('Cache write')).toBeTruthy()
    expect(segmentTotal(container, 'out')).toBe('1.0K')
  })
})
