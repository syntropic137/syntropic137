/**
 * "Which model ran?" must be answerable from every surface that shows a run.
 *
 * The API-side half of this lives in apps/syn-api/tests/test_model_visibility.py.
 * These are the CONSUMERS: the fields can be on the wire and correct while a
 * cell, badge or card never reads them, which is exactly the state issue #1094
 * describes (the session page had `agent_model_display` available and rendered
 * only the harness). So each case renders the real component a page mounts -
 * ExecutionTable, ExecutionCardList, SessionHeader, PhaseTimeline - and asserts
 * on the text a human would see.
 *
 * Fixture models are deliberately mixed (opus + sonnet): a run whose phases all
 * used one model cannot tell a rendering that shows only the first from one
 * that shows all of them.
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { ExecutionCardList } from '../ExecutionList/ExecutionCardList'
import { ExecutionTable } from '../ExecutionList/ExecutionTable'
import { PhaseTimeline } from '../ExecutionDetail/PhaseTimeline'
import { SessionCardList } from '../SessionList/SessionCardList'
import { SessionHeader } from '../SessionDetail/SessionHeader'
import { SessionTable } from '../SessionList/SessionTable'
import type {
  ExecutionDetailResponse,
  ExecutionListItem,
  SessionResponse,
  SessionSummary,
} from '../../types'

function execution(overrides: Partial<ExecutionListItem> = {}): ExecutionListItem {
  return {
    workflow_execution_id: 'exec-1',
    workflow_id: 'wf-1',
    workflow_name: 'Fix Issue',
    status: 'completed',
    started_at: null,
    completed_at: null,
    completed_phases: 2,
    total_phases: 2,
    total_tokens: 1000,
    total_tokens_display: '1.0k',
    total_cost_usd: 4.08,
    total_cost_display: '$4.08',
    duration_seconds: 60,
    duration_display: '1m',
    tool_call_count: 3,
    repos: ['syntropic137/syntropic137'],
    repos_display: 'syntropic137',
    models: ['claude-opus-4-5', 'claude-sonnet-4-5'],
    models_display: 'Opus 4.5, Sonnet 4.5',
    ...overrides,
  }
}

function renderList(rows: ExecutionListItem[]) {
  return render(
    <MemoryRouter>
      <ExecutionTable rows={rows} loading={false} emptyState={null} />
    </MemoryRouter>,
  )
}

function renderCards(rows: ExecutionListItem[]) {
  return render(
    <MemoryRouter>
      <ExecutionCardList rows={rows} loading={false} emptyState={null} />
    </MemoryRouter>,
  )
}

describe('executions list', () => {
  it('names every model the run used, not just the first', () => {
    renderList([execution()])
    expect(screen.getByText('Opus 4.5, Sonnet 4.5')).toBeTruthy()
  })

  it('offers the full model ids for the truncated label', () => {
    renderList([execution()])
    const cell = screen.getByText('Opus 4.5, Sonnet 4.5')
    expect(cell.getAttribute('title')).toBe('claude-opus-4-5\nclaude-sonnet-4-5')
  })

  it('has a Models column header operators can find', () => {
    renderList([execution()])
    expect(screen.getByText('Models')).toBeTruthy()
  })

  it('shows the models on the mobile card too', () => {
    renderCards([execution()])
    expect(screen.getByText('Models')).toBeTruthy()
    expect(screen.getByText('Opus 4.5, Sonnet 4.5')).toBeTruthy()
  })

  it('renders an em dash when the run has no priced model', () => {
    renderCards([execution({ models: [], models_display: null })])
    const label = screen.getByText('Models')
    expect(label.parentElement?.textContent).toBe('Models—')
  })
})

function session(overrides: Partial<SessionResponse> = {}): SessionResponse {
  return {
    id: 'session-abcdef123456789',
    workflow_id: null,
    workflow_name: 'Fix Issue',
    execution_id: null,
    phase_id: null,
    phase_display: null,
    milestone_id: null,
    agent_provider: 'claude',
    agent_model: 'claude-opus-4-5',
    agent_model_display: 'Opus 4.5',
    status: 'completed',
    input_tokens: 0,
    output_tokens: 0,
    cache_creation_tokens: 0,
    cache_read_tokens: 0,
    total_tokens: 0,
    total_cost_usd: 0,
    unpriced_observation_count: 0,
    cost_by_model: {},
    operations: [],
    started_at: null,
    completed_at: null,
    duration_seconds: null,
    error_message: null,
    metadata: {},
    ...overrides,
  }
}

function renderSession(s: SessionResponse) {
  return render(
    <MemoryRouter>
      <SessionHeader session={s} onViewConversationLog={() => {}} />
    </MemoryRouter>,
  )
}

describe('session detail header', () => {
  it('shows the model beside the harness, not the harness alone', () => {
    renderSession(session())
    expect(screen.getByText('Claude / Opus 4.5')).toBeTruthy()
  })

  it('uses the harness the session actually ran on', () => {
    renderSession(
      session({
        agent_provider: 'codex',
        agent_model: 'gpt-5.6-sol',
        agent_model_display: 'gpt-5.6-sol',
      }),
    )
    expect(screen.getByText('Codex / gpt-5.6-sol')).toBeTruthy()
  })

  it('still names the harness when the model is unknown', () => {
    renderSession(session({ agent_model: null, agent_model_display: null }))
    expect(screen.getByText('Claude')).toBeTruthy()
  })
})

type Phase = ExecutionDetailResponse['phases'][number]

function phase(overrides: Partial<Phase> & { workflow_phase_id: string }): Phase {
  return {
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
    provider: null,
    model: null,
    model_display: null,
    cost_by_model: {},
    ...overrides,
  } as Phase
}

function renderTimeline(phases: Phase[]) {
  return render(
    <MemoryRouter>
      <PhaseTimeline phases={phases} now={Date.now()} />
    </MemoryRouter>,
  )
}

describe('execution detail phase cards', () => {
  it('labels each phase with the harness and model it ran as', () => {
    renderTimeline([
      phase({
        workflow_phase_id: 'implement',
        name: 'Implement',
        provider: 'claude',
        model: 'claude-opus-4-5',
        model_display: 'Opus 4.5',
      }),
      phase({
        workflow_phase_id: 'verify',
        name: 'Verify',
        provider: 'codex',
        model: 'gpt-5.6-sol',
        model_display: 'gpt-5.6-sol',
      }),
    ])
    expect(screen.getByText('Claude / Opus 4.5')).toBeTruthy()
    expect(screen.getByText('Codex / gpt-5.6-sol')).toBeTruthy()
  })

  it('says nothing rather than guessing when the phase never ran', () => {
    renderTimeline([phase({ workflow_phase_id: 'plan', name: 'Plan' })])
    expect(screen.queryByText(/Claude|Codex/)).toBeNull()
  })
})


function sessionRow(overrides: Partial<SessionSummary> = {}): SessionSummary {
  return {
    id: 'session-1',
    workflow_id: null,
    workflow_name: 'Fix Issue',
    execution_id: null,
    phase_id: null,
    phase_display: null,
    status: 'completed',
    agent_provider: 'claude',
    agent_model: 'claude-opus-4-5',
    agent_model_display: 'Opus 4.5',
    repos: [],
    repos_display: null,
    total_tokens: 0,
    total_tokens_display: '0',
    total_cost_usd: 0,
    total_cost_display: '$0.00',
    duration_seconds: null,
    duration_display: '—',
    started_at: null,
    completed_at: null,
    ...overrides,
  }
}

describe('sessions list', () => {
  it('names the model beside the agent in the table', () => {
    render(
      <MemoryRouter>
        <SessionTable rows={[sessionRow()]} loading={false} emptyState={null} />
      </MemoryRouter>,
    )
    expect(screen.getByText('Claude / Opus 4.5')).toBeTruthy()
  })

  it('offers the raw model id behind the compact label', () => {
    render(
      <MemoryRouter>
        <SessionTable rows={[sessionRow()]} loading={false} emptyState={null} />
      </MemoryRouter>,
    )
    const cell = screen.getByText('Claude / Opus 4.5').closest('td')
    expect(cell?.getAttribute('title')).toBe('claude / claude-opus-4-5')
  })

  it('names the model on the mobile session card too', () => {
    render(
      <MemoryRouter>
        <SessionCardList rows={[sessionRow()]} loading={false} emptyState={null} />
      </MemoryRouter>,
    )
    expect(screen.getByText('Claude / Opus 4.5')).toBeTruthy()
  })
})
