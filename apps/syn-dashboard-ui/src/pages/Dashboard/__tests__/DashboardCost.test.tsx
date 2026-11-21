/**
 * The Dashboard's Total Tokens card shows the cost the API rendered (#897).
 *
 * It used to format `total_cost_usd` itself, so a total missing unpriced work
 * read as a confident dollar figure - `$0.0000` for a run nothing could price.
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { ANY_UNPRICED_NOTE, COST_COVERAGE_CASES } from '../../../test/costCoverageFixtures'
import type { MetricsResponse } from '../../../types'
import { Dashboard } from '../Dashboard'

const hook = vi.hoisted(() => ({ metrics: null as MetricsResponse | null }))

vi.mock('../../../hooks/useDashboardData', () => ({
  useDashboardData: () => ({
    metrics: hook.metrics,
    recentWorkflows: [],
    loading: false,
    isConnected: true,
  }),
}))
// Siblings that fetch on their own; the cost card is what is under test.
vi.mock('../ContributionHeatmap', () => ({ ContributionHeatmap: () => null }))
vi.mock('../DashboardCharts', () => ({ DashboardCharts: () => null, WorkflowStatusChart: () => null }))
vi.mock('../../../components/EventFeed', () => ({ EventFeed: () => null }))

function metricsFor(c: (typeof COST_COVERAGE_CASES)[number]): MetricsResponse {
  return {
    total_workflows: 1,
    completed_workflows: 1,
    failed_workflows: 0,
    execution_status_counts: {
      not_started: 0,
      running: 0,
      completed: 1,
      failed: 0,
      cancelled: 0,
      interrupted: 0,
    },
    total_sessions: 1,
    total_input_tokens: 10,
    total_output_tokens: 20,
    total_cache_creation_tokens: 0,
    total_cache_read_tokens: 0,
    total_tokens: 30,
    total_cost_usd: c.total_cost_usd,
    total_cost_display: c.total_cost_display,
    unpriced_observation_count: c.unpriced_observation_count,
    total_artifacts: 0,
    total_artifact_bytes: 0,
    phases: [],
  }
}

describe.each(COST_COVERAGE_CASES)('Dashboard total cost, $name', (c) => {
  it('shows the API display and the coverage note only when something was unpriced', () => {
    hook.metrics = metricsFor(c)
    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    )

    expect(screen.getByText(c.shows)).toBeTruthy()
    if (c.note) expect(screen.getByText(c.note)).toBeTruthy()
    else expect(screen.queryByText(ANY_UNPRICED_NOTE)).toBeNull()
  })
})
