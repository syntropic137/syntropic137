/**
 * The session header shows its phase's skill use (#1269) through the real
 * hook, and the line changes when the agent invokes a skill mid-phase - a
 * header that read the use once would keep warning about a skill already used.
 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { usePhaseStartPins } from '../../../hooks/usePhaseStartPins'
import type { ExecutionDetailResponse, PhaseSkillUse, SessionResponse } from '../../../types'
import { SessionHeader } from '../SessionHeader'

vi.mock('../../../api/executions', () => ({ getExecution: vi.fn() }))

import { getExecution } from '../../../api/executions'

const mockGetExecution = vi.mocked(getExecution)

const NOT_YET: PhaseSkillUse = {
  status: 'observed',
  provider: 'claude',
  declared: ['architecture'],
  invoked: [],
  declared_not_invoked: ['architecture'],
  status_display: "observed: read from this phase's Skill tool calls",
  summary_display: '0 of 1 declared skill invoked',
}

const NOW_USED: PhaseSkillUse = {
  ...NOT_YET,
  invoked: [{ name: 'architecture', count: 2 }],
  declared_not_invoked: [],
  summary_display: '1 of 1 declared skill invoked',
}

/** Test fixture: only the fields the hook reads. */
function execution(use: PhaseSkillUse, status: string): ExecutionDetailResponse {
  return {
    status,
    phases: [
      {
        session_id: 's-1',
        status,
        pinned_at_start: { provider: 'claude', requested_model: null, allowed_tools: [], skills: [] },
        start_pins_status: 'recorded',
        skill_use: use,
      },
    ],
  } as unknown as ExecutionDetailResponse
}

/** Test fixture: only the fields the header reads. */
const SESSION = {
  id: 's-1',
  status: 'running',
  execution_id: 'exec-1',
  workflow_id: null,
  phase_id: null,
  agent_provider: null,
} as unknown as SessionResponse

function Header() {
  // Live refresh slow enough that the first reading is seen before the next.
  const startPins = usePhaseStartPins('exec-1', 's-1', 5, 200)
  return <SessionHeader session={SESSION} startPins={startPins} onViewConversationLog={() => {}} />
}

describe('session header skill use', () => {
  afterEach(() => mockGetExecution.mockReset())

  it('shows the warning, then the invocation once the agent uses the skill', async () => {
    mockGetExecution
      .mockResolvedValueOnce(execution(NOT_YET, 'running'))
      .mockResolvedValue(execution(NOW_USED, 'completed'))

    const { container } = render(
      <MemoryRouter>
        <Header />
      </MemoryRouter>,
    )

    expect(await screen.findByText('0 of 1 declared skill invoked')).toBeInTheDocument()
    expect(await screen.findByText('1 of 1 declared skill invoked')).toBeInTheDocument()
    expect(screen.queryByTestId('skill-use-not-invoked')).toBeNull()
    expect(container.textContent).toContain('architecture ×2')
  })
})
