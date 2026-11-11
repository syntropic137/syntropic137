/**
 * Two runs of one workflow must read apart on the Executions list (#1075).
 *
 * Before this, every row of a workflow showed the same name, the same repos
 * and nothing about what the run was asked to do. The row now shows the API's
 * one-line `task_display` with the full `task` on hover, and it shows it as
 * TEXT: a task is author-controlled, so markup in it must arrive literally.
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { serveListEndpoint } from '../../../test/fakeListServer'
import { EXECUTIONS, matchesExecutionSearch } from '../../../test/listFixtures'
import type { ExecutionListItem } from '../../../types'
import { ExecutionList } from '../ExecutionList'

vi.mock('../../../hooks/useActivityStream', () => ({
  useActivityStream: vi.fn(() => ({ connected: true, lastEventAt: null })),
}))

type TaskFields = Pick<ExecutionListItem, 'task' | 'task_display'>
type TaskedRun = (typeof EXECUTIONS)[number] & TaskFields

const MARKUP_TASK = 'Make the <b>login</b> page\nwork again, then add a regression test for it'
const MARKUP_RUN: TaskedRun = {
  ...EXECUTIONS[0],
  workflow_execution_id: 'exec-markup',
  workflow_name: 'Same workflow',
  task: MARKUP_TASK,
  task_display: 'Make the <b>login</b> page work again, then add a regression test for it',
}
const OTHER_RUN: TaskedRun = {
  ...EXECUTIONS[1],
  workflow_execution_id: 'exec-other',
  workflow_name: 'Same workflow',
  task: 'Add dark mode',
  task_display: 'Add dark mode',
}

serveListEndpoint({
  path: '/api/v1/executions',
  collection: [MARKUP_RUN, OTHER_RUN],
  matchesSearch: matchesExecutionSearch,
})

describe('the task on each Executions row (#1075)', () => {
  it('shows task_display as literal text, with the full task as its title', async () => {
    render(
      <MemoryRouter initialEntries={['/executions']}>
        <ExecutionList />
      </MemoryRouter>,
    )

    const summary = await screen.findByText(MARKUP_RUN.task_display!)
    expect(summary.getAttribute('title')).toBe(MARKUP_TASK)
    // Rendered as text: the angle brackets are characters, not an element.
    expect(summary.querySelector('b')).toBeNull()

    expect(screen.getByText('Add dark mode').getAttribute('title')).toBe('Add dark mode')
  })
})
