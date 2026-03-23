import { describe, expect, it, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useExecutionControl, type ExecutionState } from '../useExecutionControl'

vi.mock('../../api/client', () => ({
  cancelExecution: vi.fn(),
}))

import { cancelExecution } from '../../api/client'

const mockCancel = vi.mocked(cancelExecution)

describe('useExecutionControl', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('initializes with the provided state', () => {
    const { result } = renderHook(() => useExecutionControl('exec-1', 'running'))
    expect(result.current.state).toBe('running')
    expect(result.current.error).toBeNull()
    expect(result.current.loading).toBe(false)
    expect(result.current.canCancel).toBe(true)
  })

  it('defaults to unknown state', () => {
    const { result } = renderHook(() => useExecutionControl('exec-1'))
    expect(result.current.state).toBe('unknown')
    expect(result.current.canCancel).toBe(false)
  })

  it('canCancel is true only for running/paused and not loading', () => {
    const { result: running } = renderHook(() => useExecutionControl('e', 'running'))
    expect(running.current.canCancel).toBe(true)

    const { result: paused } = renderHook(() => useExecutionControl('e', 'paused'))
    expect(paused.current.canCancel).toBe(true)

    const { result: completed } = renderHook(() => useExecutionControl('e', 'completed'))
    expect(completed.current.canCancel).toBe(false)

    const { result: failed } = renderHook(() => useExecutionControl('e', 'failed'))
    expect(failed.current.canCancel).toBe(false)
  })

  it('transitions to cancelling on successful cancel', async () => {
    mockCancel.mockResolvedValue({ success: true, execution_id: 'exec-1', state: 'cancelling', message: null })

    const { result } = renderHook(() => useExecutionControl('exec-1', 'running'))

    await act(async () => {
      result.current.cancel('test reason')
    })

    expect(mockCancel).toHaveBeenCalledWith('exec-1', 'test reason')
    expect(result.current.state).toBe('cancelling')
    expect(result.current.loading).toBe(false)
  })

  it('sets error on failed cancel', async () => {
    mockCancel.mockResolvedValue({ success: false, execution_id: 'exec-1', message: 'Not allowed', state: 'completed' })

    const { result } = renderHook(() => useExecutionControl('exec-1', 'running'))

    await act(async () => {
      result.current.cancel()
    })

    expect(result.current.error).toBe('Not allowed')
    expect(result.current.state).toBe('running')
  })

  it('sets error on network failure', async () => {
    mockCancel.mockRejectedValue(new Error('Network error'))

    const { result } = renderHook(() => useExecutionControl('exec-1', 'running'))

    await act(async () => {
      result.current.cancel()
    })

    expect(result.current.error).toBe('Network error')
  })

  it('defers to projection terminal state once caught up', async () => {
    mockCancel.mockResolvedValue({ success: true, execution_id: 'exec-1', state: 'cancelling', message: null })

    const { result, rerender } = renderHook(
      ({ state }) => useExecutionControl('exec-1', state),
      { initialProps: { state: 'running' as ExecutionState } },
    )

    // Cancel → optimistic 'cancelling'
    await act(async () => {
      result.current.cancel()
    })
    expect(result.current.state).toBe('cancelling')

    // Projection catches up → terminal state wins
    rerender({ state: 'cancelled' })
    expect(result.current.state).toBe('cancelled')
  })
})
