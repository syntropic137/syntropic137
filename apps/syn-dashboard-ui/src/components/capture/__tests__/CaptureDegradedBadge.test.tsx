/**
 * "Capture degraded" on the execution page (#1516): the header badge, its
 * per-phase indicator, and the refresh that finds a verdict recorded after
 * the page mounted.
 */

import { act, cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { CaptureStatusEntry, CaptureStatusResponse } from '../../../api/capture'
import { useExecutionCapture } from '../../../hooks/useExecutionCapture'
import { PhaseTimeline } from '../../../pages/ExecutionDetail/PhaseTimeline'
import { withPlanOfPhases } from '../../../test/phasePlanFixtures'
import type { ExecutionDetailResponse } from '../../../types'
import { CaptureDegradedBadge } from '../CaptureDegradedBadge'

type Capability = NonNullable<CaptureStatusResponse['capabilities']>[number]

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

function capability(overrides: Partial<Capability> = {}): Capability {
  return {
    execution_id: 'e-1',
    phase_id: 'p-1',
    capability: 'session-store',
    status: 'degraded',
    failed_checks: ['store_reachable'],
    doctor_exit: 3,
    capability_status_display: 'Capture degraded: store_reachable failed',
    ...overrides,
  }
}

/** Serves whatever `current` holds at the moment each request is made. */
function serve(initial: Partial<CaptureStatusResponse>) {
  const state = { current: initial }
  const fetchMock = vi.fn().mockImplementation(
    async () =>
      new Response(JSON.stringify({ total: 0, entries: [], capabilities: [], ...state.current }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
  )
  vi.stubGlobal('fetch', fetchMock)
  return { state, fetchMock }
}

function Header({ executionId, status }: { executionId: string; status: string }) {
  return <CaptureDegradedBadge degraded={useExecutionCapture(executionId, status)} />
}

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('CaptureDegradedBadge', () => {
  it('shows capture degraded with the failed check, read for this execution', async () => {
    const { fetchMock } = serve({ capabilities: [capability()] })

    render(<Header executionId="e-1" status="running" />)

    expect(await screen.findByTestId('capture-degraded-badge')).toHaveTextContent(
      'Capture degraded: store_reachable failed',
    )
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain('/capture/status?execution_id=e-1')
  })

  it('shows a teardown verdict that is degraded even with no start-up row', async () => {
    serve({
      entries: [entry({ state: 'degraded', capture_status_display: 'Capture degraded: auth_valid failed' })],
    })

    render(<Header executionId="e-1" status="completed" />)

    expect(await screen.findByTestId('capture-degraded-badge')).toHaveTextContent(
      'Capture degraded: auth_valid failed',
    )
  })

  it('counts the phases when more than one workspace degraded', async () => {
    serve({ capabilities: [capability({ phase_id: 'p-1' }), capability({ phase_id: 'p-2' })] })

    render(<Header executionId="e-1" status="running" />)

    expect(await screen.findByTestId('capture-degraded-badge')).toHaveTextContent('(2 phases)')
  })

  it('counts a phase once however many rows say it degraded', async () => {
    serve({
      capabilities: [capability(), capability()],
      entries: [entry({ state: 'degraded' }), entry({ state: 'degraded' })],
    })

    render(<Header executionId="e-1" status="completed" />)

    expect(await screen.findByTestId('capture-degraded-badge')).not.toHaveTextContent('phases)')
  })

  it('shows nothing for a healthy store or no store at all', async () => {
    const { fetchMock } = serve({
      capabilities: [capability({ status: 'ready', failed_checks: [], capability_status_display: 'Capture ready' })],
      entries: [entry({ capability_status: 'ready' })],
    })

    render(<Header executionId="e-1" status="completed" />)

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled())
    await act(async () => {})
    expect(screen.queryByTestId('capture-degraded-badge')).toBeNull()
  })
})

describe('a verdict recorded after the page mounted', () => {
  it('appears when the run finishes, without navigation or reload', async () => {
    const { state, fetchMock } = serve({})
    const { rerender } = render(<Header executionId="e-1" status="running" />)
    await act(async () => {})
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(screen.queryByTestId('capture-degraded-badge')).toBeNull()

    // The phase is torn down and its capture verdict lands; the detail page
    // re-renders with the SAME execution id and a terminal status.
    state.current = {
      entries: [entry({ state: 'degraded', capture_status_display: 'Capture degraded: store_reachable failed' })],
    }
    rerender(<Header executionId="e-1" status="completed" />)

    expect(await screen.findByTestId('capture-degraded-badge')).toHaveTextContent(
      'Capture degraded: store_reachable failed',
    )
  })

  it('appears while the run is still going, on the running poll', async () => {
    vi.useFakeTimers()
    const { state } = serve({})
    render(<Header executionId="e-1" status="running" />)
    await act(async () => {})
    expect(screen.queryByTestId('capture-degraded-badge')).toBeNull()

    // An agent launches and its start-up verdict is recorded; nothing on the
    // page changes, so only the poll can find it.
    state.current = { capabilities: [capability()] }
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
    })

    expect(screen.queryByTestId('capture-degraded-badge')).not.toBeNull()
  })
})

type Phase = ExecutionDetailResponse['phases'][number]

function phase(phaseId: string, name: string): Phase {
  return {
    phase_id: phaseId,
    name,
    status: 'completed',
    session_id: null,
    agent_session_id: null,
    input_tokens: 0,
    output_tokens: 0,
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
}

describe('CapturePhaseIndicator on the phase pipeline', () => {
  it('marks the degraded phase with its failed check and leaves the healthy one clear', () => {
    const execution = withPlanOfPhases({
      workflow_execution_id: 'e-1',
      status: 'completed',
      phases: [phase('p-1', 'Degraded phase'), phase('p-2', 'Healthy phase')],
      total_tokens: 0,
      total_cost_usd: 0,
      unpriced_observation_count: 0,
    } as unknown as ExecutionDetailResponse)

    render(
      <MemoryRouter>
        <PhaseTimeline
          execution={execution}
          now={Date.now()}
          captureDegraded={[{ phaseId: 'p-1', display: 'Capture degraded: store_reachable failed' }]}
        />
      </MemoryRouter>,
    )

    const [indicator, ...others] = screen.getAllByTestId('capture-phase-degraded')
    expect(others).toEqual([])
    expect(indicator).toHaveTextContent('Capture degraded: store_reachable failed')
    const degradedPhase = indicator.closest('.phase-with-inventory')
    expect(degradedPhase).toHaveTextContent('Degraded phase')
    expect(degradedPhase).not.toHaveTextContent('Healthy phase')
  })
})
