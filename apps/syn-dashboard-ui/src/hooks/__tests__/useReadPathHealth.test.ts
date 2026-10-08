import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'

import { CATCHING_UP, HEALTHY, makeHealth, REBUILDING_EXECUTIONS } from '../../test/readPathFixtures'
import { READ_PATH_POLL_INTERVAL_MS, useReadPathHealth } from '../useReadPathHealth'

vi.mock('../../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api')>()),
  getHealth: vi.fn(),
}))

import { getHealth } from '../../api'

const mockGetHealth = vi.mocked(getHealth)

describe('useReadPathHealth', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('asks once and does not poll while the read path is healthy', async () => {
    mockGetHealth.mockResolvedValue(HEALTHY)

    const { result } = renderHook(() => useReadPathHealth())
    await vi.waitFor(() => expect(mockGetHealth).toHaveBeenCalledTimes(1))

    await vi.advanceTimersByTimeAsync(READ_PATH_POLL_INTERVAL_MS * 5)
    expect(mockGetHealth).toHaveBeenCalledTimes(1)
    expect(result.current.rebuilding).toEqual([])
  })

  it('polls while a read model rebuilds, and stops once it has caught up', async () => {
    mockGetHealth.mockResolvedValue(CATCHING_UP)

    const { result } = renderHook(() => useReadPathHealth())
    await vi.waitFor(() => expect(result.current.rebuilding).toEqual([REBUILDING_EXECUTIONS]))

    await vi.advanceTimersByTimeAsync(READ_PATH_POLL_INTERVAL_MS)
    expect(mockGetHealth).toHaveBeenCalledTimes(2)

    mockGetHealth.mockResolvedValue(HEALTHY)
    await vi.advanceTimersByTimeAsync(READ_PATH_POLL_INTERVAL_MS)
    expect(mockGetHealth).toHaveBeenCalledTimes(3)
    await vi.waitFor(() => expect(result.current.rebuilding).toEqual([]))

    await vi.advanceTimersByTimeAsync(READ_PATH_POLL_INTERVAL_MS * 5)
    expect(mockGetHealth).toHaveBeenCalledTimes(3)
  })

  it('keeps asking after the startup gate answers without a subscription, then stops once healthy', async () => {
    mockGetHealth
      .mockResolvedValueOnce({ ...HEALTHY, status: 'starting', mode: 'degraded', subscription: null })
      .mockResolvedValueOnce(CATCHING_UP)
      .mockResolvedValue(HEALTHY)

    const { result } = renderHook(() => useReadPathHealth())
    await vi.waitFor(() => expect(mockGetHealth).toHaveBeenCalledTimes(1))

    await vi.advanceTimersByTimeAsync(READ_PATH_POLL_INTERVAL_MS)
    expect(mockGetHealth).toHaveBeenCalledTimes(2)
    await vi.waitFor(() => expect(result.current.rebuilding).toEqual([REBUILDING_EXECUTIONS]))

    await vi.advanceTimersByTimeAsync(READ_PATH_POLL_INTERVAL_MS)
    expect(mockGetHealth).toHaveBeenCalledTimes(3)
    await vi.waitFor(() => expect(result.current.rebuilding).toEqual([]))

    await vi.advanceTimersByTimeAsync(READ_PATH_POLL_INTERVAL_MS * 5)
    expect(mockGetHealth).toHaveBeenCalledTimes(3)
  })

  it('retries a failed first fetch, then stops once healthy', async () => {
    mockGetHealth
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce(CATCHING_UP)
      .mockResolvedValue(HEALTHY)

    const { result } = renderHook(() => useReadPathHealth())
    await vi.waitFor(() => expect(mockGetHealth).toHaveBeenCalledTimes(1))

    await vi.advanceTimersByTimeAsync(READ_PATH_POLL_INTERVAL_MS)
    expect(mockGetHealth).toHaveBeenCalledTimes(2)
    await vi.waitFor(() => expect(result.current.rebuilding).toEqual([REBUILDING_EXECUTIONS]))

    await vi.advanceTimersByTimeAsync(READ_PATH_POLL_INTERVAL_MS)
    expect(mockGetHealth).toHaveBeenCalledTimes(3)
    await vi.waitFor(() => expect(result.current.rebuilding).toEqual([]))

    await vi.advanceTimersByTimeAsync(READ_PATH_POLL_INTERVAL_MS * 5)
    expect(mockGetHealth).toHaveBeenCalledTimes(3)
  })

  it('keeps polling while a projection is held, even with nothing rebuilding', async () => {
    mockGetHealth.mockResolvedValue(
      makeHealth({
        status: 'held',
        held_projections: [{ projection: 'evals', event_type: 'EvalScored', global_nonce: 812 }],
        rebuilding_read_models: [],
      }),
    )

    const { result } = renderHook(() => useReadPathHealth())
    await vi.waitFor(() => expect(result.current.held).toHaveLength(1))

    await vi.advanceTimersByTimeAsync(READ_PATH_POLL_INTERVAL_MS)
    expect(mockGetHealth).toHaveBeenCalledTimes(2)
  })

  it('reads a halted subscription from halted_at, not from status', async () => {
    mockGetHealth.mockResolvedValue(makeHealth({ status: 'degraded', halted_at: 4410 }))

    const { result } = renderHook(() => useReadPathHealth())
    await vi.waitFor(() => expect(result.current.haltedAt).toBe(4410))
  })
})
