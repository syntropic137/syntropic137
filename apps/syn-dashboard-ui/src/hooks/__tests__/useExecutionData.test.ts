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
import { useExecutionStream } from '../useExecutionStream'

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

  // The #1095 defect: the poll interval was a constant and the poll had no idea
  // whether the last request had come back. Once an endpoint got slower than
  // the interval, every tick opened another connection and they stacked.
  describe('an endpoint slower than the poll interval (#1095)', () => {
    it('opens no second request while one is outstanding, however far past the interval', async () => {
      mockGetExecution.mockResolvedValueOnce(makeExecution({ status: 'running' }))

      const { result } = renderHook(() => useExecutionData('exec-1'))
      await vi.waitFor(() => expect(result.current.execution?.status).toBe('running'))
      expect(mockGetExecution).toHaveBeenCalledTimes(1)

      // The endpoint now degrades: this answer will not come back at all.
      let releaseSlow: (value: ExecutionDetailResponse) => void = () => {}
      mockGetExecution.mockReturnValue(
        new Promise<ExecutionDetailResponse>((resolve) => {
          releaseSlow = resolve
        }),
      )

      // Six poll intervals pass with that request still on the wire. A fixed 3s
      // interval that cannot see it fires on every one of them - seven calls in
      // total, which is the pile-up seen in pg_stat_activity. One poll opened
      // it; nothing may open another until it settles.
      await vi.advanceTimersByTimeAsync(18_000)
      expect(mockGetExecution).toHaveBeenCalledTimes(2)

      // And the loop is waiting, not wedged: when the answer lands it resumes.
      mockGetExecution.mockResolvedValue(makeExecution({ status: 'running' }))
      releaseSlow(makeExecution({ status: 'running' }))
      await vi.advanceTimersByTimeAsync(60_000)
      expect(mockGetExecution.mock.calls.length).toBeGreaterThan(2)
    })

    it('coalesces a burst of SSE frames into one follow-up request, not one each', async () => {
      mockGetExecution.mockResolvedValueOnce(makeExecution({ status: 'running' }))

      const { result } = renderHook(() => useExecutionData('exec-1'))
      await vi.waitFor(() => expect(result.current.execution?.status).toBe('running'))

      let releaseSlow: (value: ExecutionDetailResponse) => void = () => {}
      mockGetExecution.mockReturnValue(
        new Promise<ExecutionDetailResponse>((resolve) => {
          releaseSlow = resolve
        }),
      )
      await vi.advanceTimersByTimeAsync(4000)
      expect(mockGetExecution).toHaveBeenCalledTimes(2)

      // `OperationRecorded` arrives on every tool call an agent makes, so a
      // burst of twenty while one request is outstanding is an ordinary
      // afternoon. The poll is not the only thing that can pile up: these are
      // the second trigger on the same resource, and they must not each open a
      // connection of their own.
      const onEvent = vi.mocked(useExecutionStream).mock.calls.at(-1)?.[1]?.onEvent
      expect(onEvent).toBeDefined()
      for (let i = 0; i < 20; i++) {
        onEvent?.({
          type: 'event',
          event_type: 'OperationRecorded',
          execution_id: 'exec-1',
          data: {},
          timestamp: '2026-03-23T00:00:00Z',
        })
      }
      await vi.advanceTimersByTimeAsync(0)
      expect(mockGetExecution).toHaveBeenCalledTimes(2)

      // One follow-up when the outstanding answer lands - not twenty queued
      // behind it, which would be the pile-up deferred rather than prevented.
      mockGetExecution.mockResolvedValue(makeExecution({ status: 'running' }))
      releaseSlow(makeExecution({ status: 'running' }))
      await vi.advanceTimersByTimeAsync(0)
      expect(mockGetExecution).toHaveBeenCalledTimes(3)
    })

    it('spaces the next poll by how long the last answer took, not by the interval', async () => {
      mockGetExecution.mockResolvedValueOnce(makeExecution({ status: 'running' }))

      const { result } = renderHook(() => useExecutionData('exec-1'))
      await vi.waitFor(() => expect(result.current.execution?.status).toBe('running'))

      // 12s is four times the 3s floor and is not any constant in the
      // production code: only a gap derived from THIS latency can produce it.
      const LATENCY_MS = 12_000
      mockGetExecution.mockImplementation(
        () =>
          new Promise<ExecutionDetailResponse>((resolve) => {
            setTimeout(() => resolve(makeExecution({ status: 'running' })), LATENCY_MS)
          }),
      )

      // The floor still applies while the endpoint is unproven, so one poll
      // goes out - and stays out for twelve seconds.
      await vi.advanceTimersByTimeAsync(4000)
      expect(mockGetExecution).toHaveBeenCalledTimes(2)
      await vi.advanceTimersByTimeAsync(LATENCY_MS)

      // Now the loop has seen a 12s answer. Ten more seconds pass - three floor
      // intervals, on which a constant-paced poll would have fired three times.
      await vi.advanceTimersByTimeAsync(10_000)
      expect(mockGetExecution).toHaveBeenCalledTimes(2)

      // Crossing the observed latency is what releases the next one.
      await vi.advanceTimersByTimeAsync(3000)
      expect(mockGetExecution).toHaveBeenCalledTimes(3)
    })
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
    { status: 'interrupted', visibility: 'visible', shouldPoll: false },
    { status: 'not_started', visibility: 'visible', shouldPoll: true },
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

describe('useExecutionData recovers from a transient poll failure (#1048)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('clears the error once a later poll succeeds, and never drops the execution', async () => {
    // The page polls every 3s for the length of a run, so a single 502 in a
    // long execution is close to certain. `error` used to latch: it was set in
    // the .catch and never cleared, so the detail page rendered "Execution not
    // found" forever while the data underneath kept refreshing.
    mockGetExecution.mockResolvedValueOnce(makeExecution({ total_tokens: 100 }))

    const { result } = renderHook(() => useExecutionData('exec-1'))
    await vi.waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.error).toBeNull()

    mockGetExecution.mockRejectedValueOnce(new Error('502 Bad Gateway'))
    await vi.advanceTimersByTimeAsync(3000)
    await vi.waitFor(() => expect(result.current.error).toBe('502 Bad Gateway'))
    // The failure says the figures stopped advancing, not that they are gone.
    expect(result.current.execution?.total_tokens).toBe(100)

    mockGetExecution.mockResolvedValueOnce(makeExecution({ total_tokens: 900 }))
    await vi.advanceTimersByTimeAsync(3000)
    await vi.waitFor(() => expect(result.current.execution?.total_tokens).toBe(900))

    expect(result.current.error).toBeNull()
  })
})

describe('useExecutionData stops polling in every terminal status (#1048)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  // ExecutionStatus has seven members. Three of them can still change
  // (not_started, running, paused); the other four cannot. The hook's set held
  // only three of those four, so `interrupted` — a forceful SIGINT stop, which
  // the execution-detail projection writes and never revisits — kept the page
  // polling the API every 3 seconds for as long as the tab stayed open.
  it('stops polling an interrupted execution', async () => {
    mockGetExecution.mockResolvedValue(makeExecution({ status: 'running' }))

    const { result } = renderHook(() => useExecutionData('exec-1'))
    await vi.waitFor(() => expect(result.current.execution?.status).toBe('running'))
    expect(mockGetExecution).toHaveBeenCalledTimes(1)

    // Drive the real running -> interrupted transition while mounted.
    mockGetExecution.mockResolvedValue(makeExecution({ status: 'interrupted' }))
    await vi.advanceTimersByTimeAsync(3000)
    await vi.waitFor(() => expect(result.current.execution?.status).toBe('interrupted'))
    expect(mockGetExecution).toHaveBeenCalledTimes(2)

    // Polling must have stopped, not merely paused: five more intervals.
    await vi.advanceTimersByTimeAsync(15000)
    expect(mockGetExecution).toHaveBeenCalledTimes(2)
  })

  it.each(['completed', 'failed', 'cancelled', 'interrupted'])(
    'issues no further request for a %s execution',
    async (status) => {
      mockGetExecution.mockResolvedValue(makeExecution({ status }))

      const { result } = renderHook(() => useExecutionData('exec-1'))
      await vi.waitFor(() => expect(result.current.execution?.status).toBe(status))
      expect(mockGetExecution).toHaveBeenCalledTimes(1)

      await vi.advanceTimersByTimeAsync(15000)
      expect(mockGetExecution).toHaveBeenCalledTimes(1)
    },
  )
})
