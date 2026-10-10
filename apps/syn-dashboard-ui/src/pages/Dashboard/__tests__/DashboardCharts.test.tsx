import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { MetricsResponse } from '../../../types'
import { statusSlices, tokenSegments } from '../chartData'
import { DashboardCharts, WorkflowStatusChart } from '../DashboardCharts'

// Live shape from the owner's dashboard: cache reads are ~97% of all tokens,
// so any chart that drops them misreports almost everything.
const metrics: MetricsResponse = {
  total_workflows: 4,
  completed_workflows: 9,
  failed_workflows: 2,
  execution_status_counts: {
    not_started: 0,
    running: 1,
    completed: 9,
    failed: 2,
    cancelled: 3,
    interrupted: 4,
  },
  total_sessions: 30,
  total_input_tokens: 4_210_337,
  total_output_tokens: 61_904_118,
  total_cache_creation_tokens: 262_492_224,
  total_cache_read_tokens: 9_680_000_000,
  total_tokens: 10_008_606_679,
  total_cost_usd: 0,
  total_artifacts: 0,
  total_artifact_bytes: 0,
  phases: [],
}

describe('tokenSegments', () => {
  it('has four segments that sum to total_tokens', () => {
    const segments = tokenSegments(metrics)
    expect(segments.map((s) => s.name)).toEqual(['Input', 'Output', 'Cache read', 'Cache creation'])
    expect(segments.reduce((sum, s) => sum + s.value, 0)).toBe(metrics.total_tokens)
  })
})

describe('statusSlices', () => {
  it('has one slice per non-zero status, summing to every execution', () => {
    const slices = statusSlices(metrics.execution_status_counts)
    expect(slices.map((s) => s.name).sort()).toEqual(
      ['Cancelled', 'Completed', 'Failed', 'Interrupted', 'Running'],
    )
    const total = Object.values(metrics.execution_status_counts).reduce((a, b) => a + b, 0)
    expect(slices.reduce((sum, s) => sum + s.value, 0)).toBe(total)
  })

  it('gives every status its own colour', () => {
    const all = statusSlices({
      not_started: 1, running: 1, completed: 1, failed: 1, cancelled: 1, interrupted: 1,
    })
    expect(all).toHaveLength(6)
    expect(new Set(all.map((s) => s.fill)).size).toBe(6)
  })
})

describe('dashboard charts', () => {
  it('names the cache segments in the token chart legend', () => {
    render(<DashboardCharts metrics={metrics} />)
    expect(screen.getByText('Cache read')).toBeInTheDocument()
    expect(screen.getByText('Cache creation')).toBeInTheDocument()
  })

  it('shows cancelled, interrupted and running runs, not only completed and failed', () => {
    render(<WorkflowStatusChart metrics={metrics} />)
    for (const name of ['Completed', 'Failed', 'Cancelled', 'Interrupted', 'Running']) {
      expect(screen.getByText(name)).toBeInTheDocument()
    }
    expect(screen.queryByText('Not started')).not.toBeInTheDocument()
  })
})
