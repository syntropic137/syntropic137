/**
 * A correct refusal must not be drawn as an outage on the Executions list
 * (#1367).
 *
 * #1357 taught `StatusBadge` the difference and taught nothing else, so this
 * table showed an amber `refused` badge beside a red progress bar, in the same
 * row, about the same run. An operator scanning for outages counts red.
 *
 * The assertion is therefore "nothing in this row is red", not "this element
 * has this class": red is the claim being made, whichever element makes it,
 * and a per-class assertion goes green the moment the redness moves. The
 * platform-failure row alongside is what keeps that query honest - it must
 * still be red, and if the query stopped finding red at all it would fail
 * there first.
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { serveListEndpoint } from '../../../test/fakeListServer'
import { EXECUTIONS, matchesExecutionSearch } from '../../../test/listFixtures'
import type { FailureClassification } from '../../../types'
import { ExecutionList } from '../ExecutionList'

vi.mock('../../../hooks/useActivityStream', () => ({
  useActivityStream: vi.fn(() => ({ connected: true, lastEventAt: null })),
}))

type FailedRun = (typeof EXECUTIONS)[number] & { failure_classification: FailureClassification }

/**
 * Two runs that both failed, differing only in why.
 *
 * Built from the shared fixture rather than written out, so a row gains every
 * field the list learns to render; rows 0 and 1 are the youngest in that
 * collection and so are inside the default 24h window without the test
 * touching it.
 */
const REFUSED_RUN: FailedRun = {
  ...EXECUTIONS[0],
  workflow_execution_id: 'exec-refused',
  workflow_name: 'Refused run',
  status: 'failed',
  failure_classification: 'correct_refusal',
}
const BROKEN_RUN: FailedRun = {
  ...EXECUTIONS[1],
  workflow_execution_id: 'exec-broken',
  workflow_name: 'Broken run',
  status: 'failed',
  failure_classification: 'platform',
}

serveListEndpoint({
  path: '/api/v1/executions',
  collection: [REFUSED_RUN, BROKEN_RUN],
  matchesSearch: matchesExecutionSearch,
})

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/executions']}>
      <ExecutionList />
    </MemoryRouter>,
  )
}

/** The rendered row for a workflow name. Throws if the page has none. */
async function rowFor(workflowName: string): Promise<HTMLElement> {
  await screen.findByText(workflowName)
  const rows = Array.from(screen.getByRole('table').querySelectorAll('tbody tr'))
  const row = rows.find((candidate) => candidate.textContent?.includes(workflowName))
  if (!row) throw new Error(`No row for ${workflowName}`)
  return row as HTMLElement
}

/** Every element inside `scope` drawn in any shade of failure red. */
function redWithin(scope: HTMLElement): Element[] {
  return Array.from(scope.querySelectorAll('[class*="red-"]'))
}

describe('the Executions list and the kind of failure', () => {
  it('draws nothing in a refused run red', async () => {
    renderPage()

    expect(redWithin(await rowFor('Refused run'))).toEqual([])
  })

  it('colours the refused run amber rather than leaving it uncoloured', async () => {
    // Without this, deleting the progress bar would pass the assertion above.
    renderPage()
    const row = await rowFor('Refused run')

    expect(row.querySelectorAll('[class*="amber-"]').length).toBeGreaterThan(0)
    expect(row.textContent).toContain('refused')
  })

  it('still draws a platform failure red in the same table', async () => {
    renderPage()

    expect(redWithin(await rowFor('Broken run')).length).toBeGreaterThan(0)
  })
})
