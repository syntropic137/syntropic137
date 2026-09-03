import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useExecutionData } from '../useExecutionData'
import type { ExecutionDetailResponse, PhaseExecutionDetail } from '../../types'

vi.mock('../../api/executions', () => ({
  getExecution: vi.fn(),
}))
vi.mock('../../api/artifacts', () => ({
  getArtifact: vi.fn(),
}))
vi.mock('../useExecutionStream', () => ({
  useExecutionStream: vi.fn(() => ({ isConnected: true })),
}))

import { getExecution } from '../../api/executions'

const mockGetExecution = vi.mocked(getExecution)

function makeExecution(overrides: Partial<ExecutionDetailResponse> = {}): ExecutionDetailResponse {
  return {
    workflow_execution_id: 'exec-1',
    workflow_id: 'wf-1',
    workflow_name: 'test-workflow',
    status: 'running',
    started_at: '2026-03-23T00:00:00Z',
    completed_at: null,
    phases: [],
    total_input_tokens: 0,
    total_output_tokens: 0,
    total_cache_creation_tokens: 0,
    total_cache_read_tokens: 0,
    total_tokens: 0,
    total_cost_usd: 0,
    unpriced_observation_count: 0,
    artifact_ids: [],
    error_message: null,
    repos: [],
    workspace: null,
    ...overrides,
  }
}

// A real mid-phase shape (PhaseExecutionDetail), not the `phases: []` default
// every other fixture in this file uses. Exercises the production shape the
// execution detail page actually renders while a phase is in flight.
function makePhase(overrides: Partial<PhaseExecutionDetail> = {}): PhaseExecutionDetail {
  return {
    workflow_phase_id: 'phase-1',
    name: 'build',
    status: 'running',
    session_id: 'sess-1',
    agent_session_id: 'agent-sess-1',
    artifact_id: null,
    input_tokens: 10,
    output_tokens: 20,
    cache_creation_tokens: 0,
    cache_read_tokens: 0,
    duration_seconds: 5,
    cost_usd: 0.01,
    unpriced_observation_count: 0,
    started_at: '2026-03-23T00:00:00Z',
    completed_at: null,
    model: 'claude-sonnet-5',
    cost_by_model: {},
    ...overrides,
  }
}

describe('useExecutionData live polling (#1048)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
    Object.defineProperty(document, 'visibilityState', {
      value: 'visible',
      configurable: true,
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('refetches on an interval while the execution is running, without any SSE frame', async () => {
    mockGetExecution.mockResolvedValue(makeExecution({ total_tokens: 100 }))

    const { result } = renderHook(() => useExecutionData('exec-1'))

    await vi.waitFor(() => expect(result.current.loading).toBe(false))
    expect(mockGetExecution).toHaveBeenCalledTimes(1)

    mockGetExecution.mockResolvedValue(makeExecution({ total_tokens: 500 }))

    await vi.advanceTimersByTimeAsync(3000)
    expect(mockGetExecution).toHaveBeenCalledTimes(2)

    await vi.waitFor(() => expect(result.current.execution?.total_tokens).toBe(500))
  })

  it('polls a mid-phase execution the same as a zero-phase one', async () => {
    mockGetExecution.mockResolvedValue(makeExecution({ status: 'running', phases: [makePhase()] }))

    const { result } = renderHook(() => useExecutionData('exec-1'))
    await vi.waitFor(() => expect(result.current.execution?.phases).toHaveLength(1))
    expect(mockGetExecution).toHaveBeenCalledTimes(1)

    mockGetExecution.mockResolvedValue(
      makeExecution({ status: 'running', phases: [makePhase({ output_tokens: 999 })] }),
    )
    await vi.advanceTimersByTimeAsync(3000)
    expect(mockGetExecution).toHaveBeenCalledTimes(2)
    await vi.waitFor(() => expect(result.current.execution?.phases[0]?.output_tokens).toBe(999))
  })

  it('stops polling once a running execution actually transitions to terminal while mounted', async () => {
    mockGetExecution.mockResolvedValue(makeExecution({ status: 'running' }))

    const { result } = renderHook(() => useExecutionData('exec-1'))
    await vi.waitFor(() => expect(result.current.execution?.status).toBe('running'))
    expect(mockGetExecution).toHaveBeenCalledTimes(1)

    // Drive the real running -> terminal transition: the next poll tick
    // resolves with a terminal status while the hook is still mounted.
    mockGetExecution.mockResolvedValue(makeExecution({ status: 'completed' }))
    await vi.advanceTimersByTimeAsync(3000)
    await vi.waitFor(() => expect(result.current.execution?.status).toBe('completed'))
    expect(mockGetExecution).toHaveBeenCalledTimes(2)

    // Now prove polling actually stopped, rather than merely not having
    // started: further timer advances must not issue another request.
    await vi.advanceTimersByTimeAsync(9000)
    expect(mockGetExecution).toHaveBeenCalledTimes(2)
  })

  it('pauses while hidden and resumes with an immediate refetch when the tab becomes visible again', async () => {
    mockGetExecution.mockResolvedValue(makeExecution({ status: 'running' }))

    const { result } = renderHook(() => useExecutionData('exec-1'))
    await vi.waitFor(() => expect(result.current.execution?.status).toBe('running'))
    expect(mockGetExecution).toHaveBeenCalledTimes(1)

    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true })
    await vi.advanceTimersByTimeAsync(9000)
    expect(mockGetExecution).toHaveBeenCalledTimes(1)

    // Drive the actual hidden -> visible cycle via the real event the
    // production listener subscribes to.
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.waitFor(() => expect(mockGetExecution).toHaveBeenCalledTimes(2))

    // And prove normal interval polling resumed too, not just the one-off
    // resume fetch.
    await vi.advanceTimersByTimeAsync(3000)
    expect(mockGetExecution).toHaveBeenCalledTimes(3)
  })

  describe.each([
    { status: 'running', visibility: 'visible', shouldPoll: true },
    { status: 'running', visibility: 'hidden', shouldPoll: false },
    { status: 'paused', visibility: 'visible', shouldPoll: true },
    { status: 'completed', visibility: 'visible', shouldPoll: false },
    { status: 'failed', visibility: 'visible', shouldPoll: false },
    { status: 'cancelled', visibility: 'visible', shouldPoll: false },
    { status: 'completed', visibility: 'hidden', shouldPoll: false },
  ])(
    'invariant: polling occurs iff status is non-terminal and tab is visible ($status/$visibility)',
    ({ status, visibility, shouldPoll }) => {
      it(`${shouldPoll ? 'issues' : 'does not issue'} another request after one interval tick`, async () => {
        Object.defineProperty(document, 'visibilityState', { value: visibility, configurable: true })
        mockGetExecution.mockResolvedValue(makeExecution({ status }))

        const { result } = renderHook(() => useExecutionData('exec-1'))
        await vi.waitFor(() => expect(result.current.execution?.status).toBe(status))
        expect(mockGetExecution).toHaveBeenCalledTimes(1)

        await vi.advanceTimersByTimeAsync(3000)
        expect(mockGetExecution).toHaveBeenCalledTimes(shouldPoll ? 2 : 1)
      })
    },
  )
})
