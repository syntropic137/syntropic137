/**
 * The session header's start pins (#1454) must not freeze on a non-answer.
 *
 * A session page can open before the execution projection lists its phase,
 * and a request can fail. Neither is an answer, so the hook asks again until
 * the server gives one. Pins are then fixed, but skill use (#1269) is not, so
 * it keeps reading while the phase runs and stops once it has ended.
 */
import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { usePhaseStartPins } from '../usePhaseStartPins'
import type {
  ExecutionDetailResponse,
  PhaseSkillUse,
  PhaseStartConfig,
  StartPinsStatus,
} from '../../types'

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

/** Test fixture: only the fields the hook reads. Ended unless `running`. */
function execution(
  phases: {
    session_id: string
    pins: PhaseStartConfig | null
    status: StartPinsStatus
    skillUse?: PhaseSkillUse
  }[],
  running = false,
): ExecutionDetailResponse {
  const status = running ? 'running' : 'completed'
  return {
    status,
    phases: phases.map((p) => ({
      session_id: p.session_id,
      status,
      pinned_at_start: p.pins,
      start_pins_status: p.status,
      skill_use: p.skillUse,
    })),
  } as unknown as ExecutionDetailResponse
}

const NOT_YET: PhaseSkillUse = {
  status: 'observed',
  provider: 'claude',
  declared: ['architecture'],
  invoked: [],
  declared_not_invoked: ['architecture'],
  status_display: "observed: read from this phase's Skill tool calls",
  summary_display: '0 of 1 declared skill invoked',
}

const NOW_USED: PhaseSkillUse = {
  ...NOT_YET,
  invoked: [{ name: 'architecture', count: 2 }],
  declared_not_invoked: [],
  summary_display: '1 of 1 declared skill invoked',
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

  it('returns the phase skill use with the pins', async () => {
    mockGetExecution.mockResolvedValue(
      execution([{ session_id: 's-1', pins: PINS, status: 'recorded', skillUse: NOW_USED }]),
    )

    const { result } = renderHook(() => usePhaseStartPins('exec-1', 's-1', RETRY_MS))

    await waitFor(() => expect(result.current?.status).toBe('recorded'))
    expect(result.current?.skillUse).toEqual(NOW_USED)
  })

  it('keeps reading skill use while the phase runs, then stops when it ends', async () => {
    mockGetExecution
      .mockResolvedValueOnce(
        execution([{ session_id: 's-1', pins: PINS, status: 'recorded', skillUse: NOT_YET }], true),
      )
      .mockResolvedValue(
        execution([{ session_id: 's-1', pins: PINS, status: 'recorded', skillUse: NOW_USED }]),
      )

    // Slow enough that the first reading is seen before the next replaces it.
    const liveMs = 200
    const { result } = renderHook(() => usePhaseStartPins('exec-1', 's-1', RETRY_MS, liveMs))

    await waitFor(() => expect(result.current?.skillUse).toEqual(NOT_YET))
    await waitFor(() => expect(result.current?.skillUse).toEqual(NOW_USED))
    const calls = mockGetExecution.mock.calls.length
    await new Promise((r) => setTimeout(r, liveMs * 3))
    expect(mockGetExecution).toHaveBeenCalledTimes(calls)
  })
})
