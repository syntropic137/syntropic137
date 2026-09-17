/**
 * The Kickoff form must not dispatch a task no phase can read (#1280).
 *
 * The CLI had the same defect and is fixed the same way: `syn workflow run -t`
 * accepted a task, reported success, and started an execution that ran the
 * workflow's own prompt. This form's Task box does exactly what -t does, so it
 * gets the same two answers - refuse a task nothing consumes, warn about a
 * consumed task nobody supplied.
 *
 * Every fixture here asserts what the operator SEES and whether the execute
 * call HAPPENS, because a form that computes the right answer and posts anyway
 * is the defect, not the fix.
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { InputDeclaration, PhaseDefinition } from '../../../types'

const executeWorkflow = vi.fn()

vi.mock('../../../api/workflows', () => ({
  executeWorkflow: (...args: unknown[]) => executeWorkflow(...args),
}))

const { WorkflowExecutionForm } = await import('../WorkflowExecutionForm')

function phase(promptTemplate: string | null): PhaseDefinition {
  return {
    phase_id: 'p1',
    name: 'run',
    order: 1,
    description: null,
    agent_type: 'claude',
    prompt_template: promptTemplate,
    timeout_seconds: 600,
    allowed_tools: [],
    argument_hint: null,
    model: null,
    provider: null,
  }
}

function taskDeclaration(overrides: Partial<InputDeclaration>): InputDeclaration {
  return { name: 'task', description: null, required: false, default: null, ...overrides }
}

function runWorkflowButton(): HTMLButtonElement {
  return screen.getByRole('button', { name: /Run Workflow/ }) as HTMLButtonElement
}

function renderForm(phases: PhaseDefinition[], declarations: InputDeclaration[] = []) {
  return render(
    <WorkflowExecutionForm workflowId="wf-1" declarations={declarations} phases={phases} />,
  )
}

describe('Kickoff form task deliverability (#1280)', () => {
  beforeEach(() => {
    executeWorkflow.mockReset()
    executeWorkflow.mockResolvedValue({ execution_id: 'exec-abc123' })
  })

  it('refuses a task no phase consumes, and never posts', async () => {
    renderForm([phase('Run the QA ladder: pytest, ruff, just preflight.')])

    await userEvent.type(
      screen.getByPlaceholderText('Describe what to work on...'),
      'Measure the cold preflight p50.',
    )

    expect(screen.queryByText(/would be discarded/)).toBeTruthy()
    const runButton = runWorkflowButton()
    expect(runButton.disabled).toBe(true)
    await userEvent.click(runButton)
    expect(executeWorkflow).not.toHaveBeenCalled()
  })

  it('accepts a task on a $ARGUMENTS workflow and posts it', async () => {
    renderForm([phase('Your assignment: $ARGUMENTS')])

    await userEvent.type(
      screen.getByPlaceholderText('Describe what to work on...'),
      'Close the flaky projection test.',
    )

    expect(screen.queryByText(/would be discarded/)).toBeNull()
    await userEvent.click(runWorkflowButton())
    expect(executeWorkflow).toHaveBeenCalledWith('wf-1', {
      inputs: {},
      task: 'Close the flaky projection test.',
      provider: 'claude',
    })
  })

  it('accepts a task on a {{task}} workflow, which delivers it just as $ARGUMENTS does', async () => {
    renderForm([phase('Work on {{task}} in the checked-out repo.')])

    await userEvent.type(
      screen.getByPlaceholderText('Describe what to work on...'),
      'Close the flaky projection test.',
    )

    expect(screen.queryByText(/would be discarded/)).toBeNull()
    expect(runWorkflowButton().disabled).toBe(false)
  })

  it('warns, but still allows the run, when a phase consumes the task and none was entered', async () => {
    renderForm([phase('Your assignment: $ARGUMENTS')])

    expect(screen.queryByText(/will render empty/)).toBeTruthy()
    const runButton = runWorkflowButton()
    expect(runButton.disabled).toBe(false)
    await userEvent.click(runButton)
    expect(executeWorkflow).toHaveBeenCalledWith('wf-1', {
      inputs: {},
      task: undefined,
      provider: 'claude',
    })
  })

  it('says nothing about an empty task when the workflow declares a default for it', () => {
    renderForm([phase('Your assignment: $ARGUMENTS')], [
      taskDeclaration({ default: 'run the weekly sweep' }),
    ])

    expect(screen.queryByText(/will render empty/)).toBeNull()
  })

  it('says nothing either way on a task-free workflow with an empty Task box', () => {
    renderForm([phase('Run the QA ladder.')])

    expect(screen.queryByText(/would be discarded/)).toBeNull()
    expect(screen.queryByText(/will render empty/)).toBeNull()
    expect(runWorkflowButton().disabled).toBe(false)
  })
})
