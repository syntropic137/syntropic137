/**
 * A phase DEFINITION shows what its model alias resolves to.
 *
 * The API serves `model_display` ("opus → claude-opus-5-5"); the badge
 * renders it verbatim, and the editor repeats it under the Model field only
 * while the field still holds the saved alias - an edited value has not been
 * resolved by anything yet, so showing the old target would be a lie.
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { PhaseDefinition } from '../../../types'

vi.mock('../../../api/workflows', () => ({ updatePhasePrompt: vi.fn() }))

const { PhasePromptEditor } = await import('../PhasePromptEditor')

function phase(overrides: Partial<PhaseDefinition>): PhaseDefinition {
  return {
    phase_id: 'p1',
    name: 'implement',
    order: 1,
    description: null,
    agent_type: 'claude',
    prompt_template: 'do it',
    timeout_seconds: 600,
    allowed_tools: [],
    argument_hint: null,
    model: null,
    provider: null,
    ...overrides,
  }
}

const OPUS = phase({
  model: 'opus',
  provider: 'claude',
  resolved_model: 'claude-opus-5-5',
  resolution_basis: 'expected',
  model_display: 'opus → claude-opus-5-5',
})

describe('alias resolution on the phase definition', () => {
  it('badge shows the alias and what it resolves to', () => {
    render(<PhasePromptEditor phase={OPUS} workflowId="wf-1" />)
    expect(screen.getByText('opus → claude-opus-5-5')).toBeTruthy()
  })

  it('badge shows a concrete model as-is', () => {
    render(<PhasePromptEditor phase={phase({ model: 'gpt-6-sol', model_display: 'gpt-6-sol', provider: 'codex' })} workflowId="wf-1" />)
    expect(screen.getByText('gpt-6-sol')).toBeTruthy()
  })

  it('falls back to the raw model when the API sends no display', () => {
    render(<PhasePromptEditor phase={phase({ model: 'sonnet' })} workflowId="wf-1" />)
    expect(screen.getByText('sonnet')).toBeTruthy()
  })

  it('editor hints the resolution only while the saved alias is unchanged', async () => {
    const user = userEvent.setup()
    render(<PhasePromptEditor phase={OPUS} workflowId="wf-1" />)
    await user.click(screen.getByRole('button', { name: /Edit/ }))

    expect(screen.getByTestId('model-resolution-hint').textContent).toBe('opus → claude-opus-5-5')

    const input = screen.getByPlaceholderText(/e\.g\. opus/)
    await user.clear(input)
    await user.type(input, 'sonnet')
    expect(screen.queryByTestId('model-resolution-hint')).toBeNull()
  })

  it('editor hides the hint once the provider changes', async () => {
    const user = userEvent.setup()
    render(<PhasePromptEditor phase={OPUS} workflowId="wf-1" />)
    await user.click(screen.getByRole('button', { name: /Edit/ }))
    expect(screen.getByTestId('model-resolution-hint')).toBeTruthy()

    await user.selectOptions(screen.getByDisplayValue(/Claude/i), 'codex')
    expect(screen.queryByTestId('model-resolution-hint')).toBeNull()
  })
})
