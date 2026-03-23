import { describe, expect, it, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useWorkflowData } from '../useWorkflowData'

vi.mock('../../api/workflows', () => ({
  getWorkflow: vi.fn(),
  getWorkflowHistory: vi.fn(),
}))

vi.mock('../../api/executions', () => ({
  listExecutions: vi.fn(),
}))

vi.mock('../../api/observability', () => ({
  getMetrics: vi.fn(),
}))

vi.mock('../../api/artifacts', () => ({
  listArtifacts: vi.fn(),
}))

import { getWorkflow, getWorkflowHistory } from '../../api/workflows'
import { listExecutions } from '../../api/executions'
import { getMetrics } from '../../api/observability'
import { listArtifacts } from '../../api/artifacts'

describe('useWorkflowData', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('fetches all data in parallel on mount', async () => {
    vi.mocked(getWorkflow).mockResolvedValue({ workflow_id: 'wf-1' } as never)
    vi.mocked(getMetrics).mockResolvedValue({ total_tokens: 0 } as never)
    vi.mocked(getWorkflowHistory).mockResolvedValue({ entries: [] } as never)
    vi.mocked(listArtifacts).mockResolvedValue([])
    vi.mocked(listExecutions).mockResolvedValue([])

    const { result } = renderHook(() => useWorkflowData('wf-1'))

    expect(result.current.loading).toBe(true)

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    expect(result.current.workflow).toEqual({ workflow_id: 'wf-1' })
    expect(result.current.error).toBeNull()
    expect(getWorkflow).toHaveBeenCalledWith('wf-1')
    expect(getMetrics).toHaveBeenCalledWith('wf-1')
  })

  it('sets error on failure', async () => {
    vi.mocked(getWorkflow).mockRejectedValue(new Error('Not found'))
    vi.mocked(getMetrics).mockResolvedValue({} as never)
    vi.mocked(getWorkflowHistory).mockResolvedValue({} as never)
    vi.mocked(listArtifacts).mockResolvedValue([])
    vi.mocked(listExecutions).mockResolvedValue([])

    const { result } = renderHook(() => useWorkflowData('wf-1'))

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    expect(result.current.error).toBe('Not found')
  })

  it('does not fetch when workflowId is undefined', () => {
    renderHook(() => useWorkflowData(undefined))
    expect(getWorkflow).not.toHaveBeenCalled()
  })
})
