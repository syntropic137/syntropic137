/**
 * The timeline shows every declared phase, not only the ones that started
 * (feedback cee46909).
 *
 * The fixture is the run the server's `phase_plan` describes for a review that
 * certified early on a resumed execution: one phase inherited from the parent,
 * one that ran here, two repair rounds skipped, one still to come. `phases`
 * holds only the one that ran, so a timeline drawn from `phases` shows one card
 * and every assertion below about the other four fails.
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { PhaseTimeline } from '../PhaseTimeline'
import type { ExecutionDetailResponse } from '../../../types'

type Phase = ExecutionDetailResponse['phases'][number]
type Planned = ExecutionDetailResponse['phase_plan'][number]

const ranHere = {
  workflow_phase_id: 'review',
  name: 'Review',
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
} as unknown as Phase

const plan: Planned[] = [
  { phase_id: 'implement', name: 'Implement', status: 'inherited', status_display: 'Inherited (completed earlier)' },
  { phase_id: 'review', name: 'Review', status: 'completed', status_display: 'Completed' },
  { phase_id: 'fix_2', name: 'Fix 2', status: 'skipped', status_display: 'Skipped (not needed)' },
  { phase_id: 'reverify_2', name: 'Reverify 2', status: 'skipped', status_display: 'Skipped (not needed)' },
  { phase_id: 'report', name: 'Report', status: 'pending', status_display: 'Pending' },
]

function renderTimeline() {
  const execution = {
    workflow_execution_id: 'exec-1',
    workflow_id: 'wf-1',
    workflow_name: 'Run',
    status: 'running',
    phases: [ranHere],
    phase_plan: plan,
    total_phases: 5,
    phase_progress: { completed: 2, skipped: 2, possible: 3, remaining_possible: 1, percent: 67, display: 'phase 3 of up to 3 (2 phases not needed)' },
    total_input_tokens: 0,
    total_output_tokens: 0,
    total_cache_creation_tokens: 0,
    total_cache_read_tokens: 0,
    total_tokens: 0,
    total_cost_usd: 0,
    unpriced_observation_count: 0,
    artifact_ids: [],
    repos: [],
  } as unknown as ExecutionDetailResponse
  return render(
    <MemoryRouter>
      <PhaseTimeline execution={execution} now={Date.now()} />
    </MemoryRouter>,
  )
}

function plannedCard(name: string): HTMLElement {
  const card = screen.getByText(name).closest('.phase-planned')
  if (!(card instanceof HTMLElement)) throw new Error(`no planned-phase card for ${name}`)
  return card
}

describe('PhaseTimeline draws the whole phase plan', () => {
  it('shows every declared phase, in plan order', () => {
    renderTimeline()
    const names = plan.map((p) => p.name)
    const rendered = names.map((n) => screen.getByText(n))
    // Document order is plan order.
    for (let i = 1; i < rendered.length; i++) {
      expect(rendered[i - 1].compareDocumentPosition(rendered[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    }
  })

  it('counts the plan in the header, not only the phases that started', () => {
    renderTimeline()
    expect(screen.getByText('5 phases')).toBeInTheDocument()
  })

  it('draws a phase still to come as pending, muted', () => {
    renderTimeline()
    const card = plannedCard('Report')
    expect(card).toHaveClass('phase-planned--pending')
    expect(card).toHaveTextContent('Pending')
  })

  it('draws a skipped repair round as skipped, not pending', () => {
    renderTimeline()
    for (const name of ['Fix 2', 'Reverify 2']) {
      const card = plannedCard(name)
      expect(card).toHaveClass('phase-planned--skipped')
      expect(card).not.toHaveClass('phase-planned--pending')
      expect(card).toHaveTextContent('Skipped (not needed)')
    }
  })

  it('draws an inherited phase as inherited', () => {
    renderTimeline()
    const card = plannedCard('Implement')
    expect(card).toHaveClass('phase-planned--inherited')
    expect(card).toHaveTextContent('Inherited (completed earlier)')
  })

  it('draws the phase that ran here as its full card, with its sessions link', () => {
    renderTimeline()
    expect(screen.getByText('Review').closest('.phase-planned')).toBeNull()
    expect(screen.getByLabelText('Sessions for phase Review')).toBeInTheDocument()
  })
})
