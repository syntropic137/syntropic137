/**
 * Rendered parity (#1398 row 9): the Sessions view, fed the API-generated
 * fixture through a limit-honouring replay, never claims completeness while
 * any section is still pending, and after Load more reaches exactly the golden
 * inventory before it may say Complete.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'

import { createReplay, fixture } from '../../../api/__tests__/inventoryReplay'
import { SessionInventory } from '../SessionInventory'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const reconciled = (status: Record<string, unknown>) => {
  const snapshot = status['snapshot'] as Record<string, unknown>
  const summary = status['summary'] as Record<string, unknown>
  return {
    ...status,
    snapshot: { ...snapshot, coverage: { ...(snapshot['coverage'] as object), state: 'reconciled' } },
    summary: { ...summary, complete: true, coverage_state: 'reconciled' },
  }
}

const complete = () => document.querySelector('[data-state="complete"]')

function renderedNodeIds(): string[] {
  const ids = new Set<string>()
  document.querySelectorAll('[data-inventory-row]').forEach(row => {
    const namespace = row.querySelector('.si-badge')?.textContent
    const id = row.querySelector('.si-id')?.textContent
    ids.add(`${namespace}/${id}`)
  })
  return [...ids].sort()
}

it('reaches the golden inventory through Load more and only then claims complete', async () => {
  const replay = createReplay(reconciled)
  vi.stubGlobal('fetch', vi.fn(replay.fetch))
  render(<MemoryRouter initialEntries={[`/executions/${fixture.execution_id}`]}>
    <Routes><Route path="/executions/:id" element={<SessionInventory executionId={fixture.execution_id} budget={2} />} /></Routes>
  </MemoryRouter>)
  await screen.findByText(/More available in this revision/)
  let rounds = 0
  while (screen.queryByText('Load more')) {
    expect(complete()).toBeNull()
    expect(document.querySelector('[data-state="coverage-complete-not-loaded"]')).toBeTruthy()
    fireEvent.click(screen.getByText('Load more'))
    await waitFor(() => expect(screen.queryByText('Loading more...')).toBeNull())
    expect(++rounds).toBeLessThan(50)
  }
  expect(rounds).toBeGreaterThan(1)
  expect(Math.max(...replay.limits)).toBeLessThanOrEqual(2)
  expect(complete()).toBeTruthy()
  expect(screen.queryByText(/provisional/)).toBeNull()
  const expected = fixture.expected as { node_ids: string[]; gaps: unknown[]; counts_display: string }
  expect(renderedNodeIds()).toEqual(expected.node_ids)
  expect(screen.getByText(`Gaps (${expected.gaps.length})`)).toBeTruthy()
  expect(screen.getByText(expected.counts_display)).toBeTruthy()
})

it('an open-coverage fixture never claims complete even when fully loaded', async () => {
  vi.stubGlobal('fetch', vi.fn(createReplay().fetch))
  render(<MemoryRouter initialEntries={[`/executions/${fixture.execution_id}`]}>
    <Routes><Route path="/executions/:id" element={<SessionInventory executionId={fixture.execution_id} />} /></Routes>
  </MemoryRouter>)
  await screen.findByText(fixture.expected['counts_display'] as string)
  expect(screen.queryByText('Load more')).toBeNull()
  expect(complete()).toBeNull()
  expect(document.querySelector('[data-state="partial"]')).toBeTruthy()
  expect(renderedNodeIds()).toEqual(fixture.expected['node_ids'])
})
