/**
 * Execution provenance (#1307, #1030, #759, #1454): what a run was asked to do,
 * and what each phase had when it started.
 *
 * Each "not recorded" case is paired with a recorded one, because a component
 * that always said "not recorded" would pass a test of that path alone.
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { DispatchedTask } from '../provenance/DispatchedTask'
import { PhaseStartPins } from '../provenance/PhaseStartPins'
import { PhaseTimeline } from '../../pages/ExecutionDetail/PhaseTimeline'
import type { ExecutionDetailResponse, PhaseStartConfig } from '../../types'

/** Indentation, a blank line and trailing spaces: all of it is the prompt. */
const TASK = 'Fix #1030:\n\n    keep this indented\n\tand this tabbed  \nend'

describe('DispatchedTask', () => {
  it('renders the task verbatim, whitespace included', () => {
    render(<DispatchedTask task={TASK} />)
    const text = screen.getByTestId('dispatched-task-text')
    expect(text.tagName).toBe('PRE')
    expect(text.textContent).toBe(TASK)
  })

  it('opens a short task and collapses a long one by default', () => {
    const { container, rerender } = render(<DispatchedTask task={TASK} />)
    expect(container.querySelector('details')?.open).toBe(true)

    const long = Array.from({ length: 40 }, (_, i) => `line ${i}`).join('\n')
    rerender(<DispatchedTask key="long" task={long} />)
    const details = container.querySelector('details')
    expect(details?.open).toBe(false)
    // Collapsed, not truncated: the whole prompt is still there to expand.
    expect(screen.getByTestId('dispatched-task-text').textContent).toBe(long)
  })

  it('says a run with no task had none, rather than rendering nothing', () => {
    render(<DispatchedTask task={null} />)
    expect(screen.getByText('No task was recorded for this run.')).toBeTruthy()
    expect(screen.queryByTestId('dispatched-task-text')).toBeNull()
  })
})

const PINS: PhaseStartConfig = {
  provider: 'claude',
  requested_model: 'claude-opus-5-5',
  allowed_tools: ['Read', 'Bash(git log:*)'],
  skills: [
    {
      name: 'architecture',
      version: 'v2.3.1',
      resolved_sha: '9f1c0de4',
      source_url: 'https://github.com/syntropic137/software-leverage-points',
    },
  ],
}

describe('PhaseStartPins', () => {
  it('shows the pinned model, tools and skill versions', () => {
    const { container } = render(<PhaseStartPins pins={PINS} />)
    const text = container.textContent ?? ''
    expect(text).toContain('claude-opus-5-5')
    expect(text).toContain('Bash(git log:*)')
    expect(text).toContain('architecture')
    expect(text).toContain('v2.3.1')
    expect(text).not.toContain('not recorded')
  })

  it('says "not recorded" for a run from before #1454, and guesses nothing', () => {
    const { container } = render(<PhaseStartPins pins={null} />)
    expect(container.textContent).toBe('Start config: not recorded')
  })

  it('does not read an empty tool list as "no tools"', () => {
    const { container } = render(<PhaseStartPins pins={{ ...PINS, allowed_tools: [] }} />)
    expect(container.textContent).toContain('no restriction declared (harness default)')
  })
})

describe('PhaseTimeline carries each phase its own pins', () => {
  function phase(id: string, pins: PhaseStartConfig | null): ExecutionDetailResponse['phases'][number] {
    return {
      workflow_phase_id: id,
      name: id,
      status: 'completed',
      session_id: null,
      agent_session_id: null,
      artifact_id: null,
      input_tokens: 0,
      output_tokens: 0,
      cache_creation_tokens: 0,
      cache_read_tokens: 0,
      duration_seconds: 1,
      cost_usd: 0,
      unpriced_observation_count: 0,
      started_at: null,
      completed_at: null,
      model: null,
      requested_model: null,
      model_display: 'unknown',
      cost_by_model: {},
      pinned_at_start: pins,
    }
  }

  it('renders the recorded phase pins and the unrecorded one as not recorded', () => {
    const execution = {
      workflow_execution_id: 'exec-1',
      workflow_id: 'wf',
      workflow_name: 'wf',
      status: 'completed',
      phases: [phase('research', PINS), phase('legacy', null)],
      total_phases: 2,
      completed_phases: 2,
      total_input_tokens: 0,
      total_output_tokens: 0,
      total_cache_creation_tokens: 0,
      total_cache_read_tokens: 0,
      total_tokens: 0,
      total_cost_usd: 0,
      unpriced_observation_count: 0,
      artifact_ids: [],
    } as unknown as ExecutionDetailResponse // test fixture: only the fields the timeline reads
    const { container } = render(
      <MemoryRouter>
        <PhaseTimeline execution={execution} now={0} />
      </MemoryRouter>,
    )
    const text = container.textContent ?? ''
    expect(text).toContain('v2.3.1')
    expect(text.match(/Start config: not recorded/g)).toHaveLength(1)
  })
})
