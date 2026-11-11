/**
 * The session header names its phase by the backend's phase_display (#1029),
 * which is the name the execution recorded, not the raw phase id.
 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { SessionResponse } from '../../../types'
import { SessionHeader } from '../SessionHeader'

/** Test fixture: only the fields the header reads. */
const SESSION = {
  id: 's-1',
  status: 'completed',
  execution_id: null,
  workflow_id: null,
  phase_id: 'fix',
  phase_display: 'Address what verification found',
  agent_provider: null,
} as unknown as SessionResponse

describe('session header phase', () => {
  it('shows the phase display, keeping the id as its title', () => {
    render(
      <MemoryRouter>
        <SessionHeader session={SESSION} onViewConversationLog={() => {}} />
      </MemoryRouter>,
    )

    const phase = screen.getByText('Phase: Address what verification found')
    expect(phase.getAttribute('title')).toBe('fix')
    expect(screen.queryByText('Phase: fix')).toBeNull()
  })
})
