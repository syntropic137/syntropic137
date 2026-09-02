import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useExecutionData } from '../useExecutionData'
import type { ExecutionDetailResponse } from '../../types'

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

  it('stops polling once the execution reaches a terminal status', async () => {
    mockGetExecution.mockResolvedValue(makeExecution({ status: 'completed' }))

    const { result } = renderHook(() => useExecutionData('exec-1'))

    // Wait for the resolved fetch to actually land in state — polling is
    // gated on `execution`, not on the mock having been invoked.
    await vi.waitFor(() => expect(result.current.execution?.status).toBe('completed'))
    expect(mockGetExecution).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(9000)
    expect(mockGetExecution).toHaveBeenCalledTimes(1)
  })

  it('pauses polling while the tab is hidden', async () => {
    mockGetExecution.mockResolvedValue(makeExecution())

    const { result } = renderHook(() => useExecutionData('exec-1'))
    await vi.waitFor(() => expect(result.current.execution?.status).toBe('running'))
    expect(mockGetExecution).toHaveBeenCalledTimes(1)

    Object.defineProperty(document, 'visibilityState', {
      value: 'hidden',
      configurable: true,
    })

    await vi.advanceTimersByTimeAsync(9000)
    expect(mockGetExecution).toHaveBeenCalledTimes(1)
  })
})
