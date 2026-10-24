import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { CaptureStatusEntry } from '../../../api/capture'
import { CaptureDegradedBadge } from '../CaptureDegradedBadge'

function entry(overrides: Partial<CaptureStatusEntry> = {}): CaptureStatusEntry {
  return {
    session_id: 's-1',
    execution_id: 'e-1',
    phase_id: 'p-1',
    state: 'captured',
    needs_backfill: false,
    failed_checks: [],
    capture_status_display: 'Captured',
    ...overrides,
  }
}

function respondWith(entries: CaptureStatusEntry[]) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ total: entries.length, entries }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => vi.unstubAllGlobals())

describe('CaptureDegradedBadge', () => {
  it('shows capture degraded with the failed check, read for this execution', async () => {
    const fetchMock = respondWith([
      entry({
        state: 'degraded',
        capability_status: 'degraded',
        failed_checks: ['store_reachable'],
        capture_status_display: 'Capture degraded: store_reachable failed',
      }),
    ])

    render(<CaptureDegradedBadge executionId="e-1" />)

    expect(await screen.findByTestId('capture-degraded-badge')).toHaveTextContent(
      'Capture degraded: store_reachable failed'
    )
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain('/capture/status?execution_id=e-1')
  })

  it('counts the phases when more than one workspace degraded', async () => {
    respondWith([
      entry({ phase_id: 'p-1', state: 'degraded', capture_status_display: 'Capture degraded: store_reachable failed' }),
      entry({ phase_id: 'p-2', state: 'degraded', capture_status_display: 'Capture degraded: store_reachable failed' }),
    ])

    render(<CaptureDegradedBadge executionId="e-1" />)

    expect(await screen.findByTestId('capture-degraded-badge')).toHaveTextContent('(2 phases)')
  })

  it('shows nothing for a healthy store', async () => {
    const fetchMock = respondWith([entry({ capability_status: 'ready' })])

    render(<CaptureDegradedBadge executionId="e-1" />)

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled())
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(screen.queryByTestId('capture-degraded-badge')).toBeNull()
  })
})
