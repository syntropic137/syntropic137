/**
 * The Phase Pipeline names the model that RAN, never the alias it was asked for
 * (ADR-067 D9).
 *
 * The card used to print the alias ("opus", "gpt-sol") under each phase, which
 * proves nothing: an alias is a pointer and where it points moves. These cases
 * pin the observed id as the primary label, "unknown (requested: X)" when the
 * harness reported nothing, and the alias only ever as "requested: X".
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { UNATTRIBUTED_MODEL_KEY, UNATTRIBUTED_MODEL_LABEL } from '../../../constants/models'
import type { ExecutionDetailResponse } from '../../../types'
import { PhaseTimeline } from '../PhaseTimeline'

type Phase = ExecutionDetailResponse['phases'][number]

function phase(overrides: Partial<Phase>): Phase {
  return {
    workflow_phase_id: 'p1',
    name: 'Phase',
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
    ...overrides,
  }
}

function renderPhases(phases: Phase[]) {
  const execution = {
    workflow_execution_id: 'exec-1',
    workflow_id: 'wf-1',
    workflow_name: 'Run',
    status: 'completed',
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
  } as unknown as ExecutionDetailResponse
  return render(
    <MemoryRouter>
      <PhaseTimeline execution={execution} now={Date.now()} />
    </MemoryRouter>,
  )
}

/** Primary label of every phase card's model, in order. */
function primaryModelLabels(): string[] {
  return screen
    .getAllByTestId('observed-model')
    .map((el) => el.firstElementChild?.textContent ?? '')
}

describe('Phase Pipeline model label', () => {
  it('shows the observed explicit id, with the alias only as requested context', () => {
    renderPhases([
      phase({
        model: 'claude-opus-5-5',
        requested_model: 'opus',
        model_display: 'claude-opus-5-5',
        cost_by_model: { 'claude-opus-5-5': '0.5' },
      }),
    ])
    expect(primaryModelLabels()).toEqual(['claude-opus-5-5'])
    expect(screen.getByText('requested: opus')).toBeTruthy()
    // The alias never stands alone as if it were the model.
    expect(screen.queryByText('opus')).toBeNull()
    // No shortening: the full id survives in the cost rows too.
    expect(screen.queryByText('opus-5-5')).toBeNull()
  })

  it('shows "unknown (requested: gpt-sol)" when no model was observed', () => {
    renderPhases([
      phase({
        model: null,
        requested_model: 'gpt-sol',
        model_display: 'unknown (requested: gpt-sol)',
        cost_by_model: { [UNATTRIBUTED_MODEL_KEY]: '0.1' },
      }),
    ])
    expect(primaryModelLabels()).toEqual(['unknown (requested: gpt-sol)'])
    expect(screen.queryByText('gpt-sol')).toBeNull()
    // Not repeated as a second line: the display already carries it.
    expect(screen.queryByText('requested: gpt-sol')).toBeNull()
    expect(screen.getByText(UNATTRIBUTED_MODEL_LABEL)).toBeTruthy()
    expect(screen.queryByText(UNATTRIBUTED_MODEL_KEY)).toBeNull()
  })

  it('omits the requested line when the observed id is what was requested', () => {
    renderPhases([
      phase({
        model: 'gpt-6-sol',
        requested_model: 'gpt-6-sol',
        model_display: 'gpt-6-sol',
      }),
    ])
    expect(primaryModelLabels()).toEqual(['gpt-6-sol'])
    expect(screen.queryByText(/requested:/)).toBeNull()
  })

  it('never renders a bare alias as any phase model', () => {
    const aliases = ['opus', 'sonnet', 'haiku', 'fable', 'gpt-sol']
    renderPhases(
      aliases.map((alias, i) =>
        phase({
          workflow_phase_id: `p${i}`,
          model: null,
          requested_model: alias,
          model_display: `unknown (requested: ${alias})`,
        }),
      ),
    )
    for (const label of primaryModelLabels()) {
      expect(aliases).not.toContain(label)
    }
  })
})
