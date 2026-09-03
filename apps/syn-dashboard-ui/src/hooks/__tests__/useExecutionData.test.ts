/**
 * Live-update behaviour of the execution detail hook (issue #1048).
 *
 * These tests deliberately assert on the numbers the detail page renders
 * (`execution.total_tokens`, `execution.total_cost_usd`) rather than on
 * "was useRefetchWhileRunning called". The SSE stream is stubbed to deliver
 * nothing at all, so any change in those numbers can only have come from a
 * poll.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import type { ExecutionDetailResponse } from '../../types'
import { useExecutionData } from '../useExecutionData'

vi.mock('../../api/executions', () => ({ getExecution: vi.fn() }))
vi.mock('../../api/artifacts', () => ({ getArtifact: vi.fn() }))

// Stubbed to never emit a frame: the detail page's only other live path is
// SSE, so silencing it isolates polling as the cause of any refresh.
vi.mock('../useExecutionStream', () => ({
  useExecutionStream: () => ({ isConnected: true, events: [], latestEvent: null }),
}))

import { getExecution } from '../../api/executions'

const mockGetExecution = vi.mocked(getExecution)

/** The cadence useRefetchWhileRunning polls at. */
const POLL_INTERVAL_MS = 3000

function makeExecution(overrides: Partial<ExecutionDetailResponse> = {}): ExecutionDetailResponse {
  return {
    workflow_execution_id: 'exec-1',
    workflow_id: 'wf-1',
    workflow_name: 'demo',
    status: 'running',
    started_at: '2026-03-23T00:00:00Z',
    completed_at: null,
    phases: [],
    total_input_tokens: 0,
    total_output_tokens: 0,
    total_cache_creation_tokens: 0,
    total_cache_read_tokens: 0,
    total_tokens: 100,
    total_cost_usd: 0.5,
    unpriced_observation_count: 0,
    artifact_ids: [],
    error_message: null,
    repos: [],
    workspace: null,
    ...overrides,
  }
}

/**
 * First fetch returns the baseline numbers, every later fetch returns values
 * that cannot appear unless the hook fetched a second time.
 */
function serveThenTick(status: string): void {
  mockGetExecution
    .mockResolvedValueOnce(makeExecution({ status }))
    .mockResolvedValue(makeExecution({ status, total_tokens: 4242, total_cost_usd: 13.37 }))
}

/** Mount and let the initial fetch settle. */
async function mountSettled() {
  const rendered = renderHook(() => useExecutionData('exec-1'))
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })
  return rendered
}

describe('useExecutionData live updates', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('ticks tokens and cost while running, with no SSE frame', async () => {
    serveThenTick('running')

    const { result } = await mountSettled()
    expect(result.current.execution?.total_tokens).toBe(100)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    })

    expect(result.current.execution?.total_tokens).toBe(4242)
    expect(result.current.execution?.total_cost_usd).toBe(13.37)
  })

  it('ticks while paused, not only while running', async () => {
    serveThenTick('paused')

    const { result } = await mountSettled()
    expect(result.current.execution?.total_tokens).toBe(100)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    })

    expect(result.current.execution?.total_tokens).toBe(4242)
  })

  it('stops polling once the execution is completed', async () => {
    serveThenTick('completed')

    await mountSettled()
    expect(mockGetExecution).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 5)
    })

    expect(mockGetExecution).toHaveBeenCalledTimes(1)
  })

  it('stops polling once the execution is interrupted', async () => {
    serveThenTick('interrupted')

    await mountSettled()
    expect(mockGetExecution).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 5)
    })

    expect(mockGetExecution).toHaveBeenCalledTimes(1)
  })
})
