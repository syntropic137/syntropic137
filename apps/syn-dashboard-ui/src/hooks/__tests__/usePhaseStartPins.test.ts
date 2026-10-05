/**
 * The session header's start pins (#1454) must not freeze on a non-answer.
 *
 * A session page can open before the execution projection lists its phase,
 * and a request can fail. Neither is an answer, so the hook asks again until
 * the server gives one, and only then stops.
 */
import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { usePhaseStartPins } from '../usePhaseStartPins'
import type { ExecutionDetailResponse, PhaseStartConfig, StartPinsStatus } from '../../types'

vi.mock('../../api/executions', () => ({
  getExecution: vi.fn(),
}))

import { getExecution } from '../../api/executions'

const mockGetExecution = vi.mocked(getExecution)

const PINS: PhaseStartConfig = {
  provider: 'claude',
  requested_model: 'opus',
  allowed_tools: ['Read'],
  skills: [],
}

/** Test fixture: only the fields the hook reads. */
function execution(
  phases: { session_id: string; pins: PhaseStartConfig | null; status: StartPinsStatus }[],
): ExecutionDetailResponse {
  return {
    phases: phases.map((p) => ({
      session_id: p.session_id,
      pinned_at_start: p.pins,
      start_pins_status: p.status,
    })),
  } as unknown as ExecutionDetailResponse
}

const RETRY_MS = 5

describe('usePhaseStartPins', () => {
  afterEach(() => {
    mockGetExecution.mockReset()
  })

  it('picks up the pins once the phase reaches the execution projection', async () => {
    mockGetExecution
      .mockResolvedValueOnce(execution([]))
      .mockResolvedValue(execution([{ session_id: 's-1', pins: PINS, status: 'recorded' }]))

    const { result } = renderHook(() => usePhaseStartPins('exec-1', 's-1', RETRY_MS))

    await waitFor(() => expect(result.current).toEqual({ pins: PINS, status: 'recorded' }))
    expect(mockGetExecution.mock.calls.length).toBeGreaterThanOrEqual(2)
  })

  it('recovers from a failed request without a reload', async () => {
    mockGetExecution
      .mockRejectedValueOnce(new Error('502'))
      .mockResolvedValue(execution([{ session_id: 's-1', pins: PINS, status: 'recorded' }]))

    const { result } = renderHook(() => usePhaseStartPins('exec-1', 's-1', RETRY_MS))

    await waitFor(() => expect(result.current).toEqual({ pins: PINS, status: 'recorded' }))
  })

  it('reports unavailable while the server cannot read the start event, then the answer', async () => {
    mockGetExecution
      .mockResolvedValueOnce(execution([{ session_id: 's-1', pins: null, status: 'unavailable' }]))
      .mockResolvedValue(execution([{ session_id: 's-1', pins: null, status: 'not_recorded' }]))

    const { result } = renderHook(() => usePhaseStartPins('exec-1', 's-1', RETRY_MS))

    await waitFor(() => expect(result.current).toEqual({ pins: null, status: 'not_recorded' }))
  })

  it('stops asking once the server has answered', async () => {
    mockGetExecution.mockResolvedValue(
      execution([{ session_id: 's-1', pins: null, status: 'not_recorded' }]),
    )

    const { result } = renderHook(() => usePhaseStartPins('exec-1', 's-1', RETRY_MS))

    await waitFor(() => expect(result.current?.status).toBe('not_recorded'))
    await new Promise((r) => setTimeout(r, RETRY_MS * 10))
    expect(mockGetExecution).toHaveBeenCalledTimes(1)
  })
})
