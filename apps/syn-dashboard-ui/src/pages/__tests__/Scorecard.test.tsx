/**
 * The Scorecard page renders what `/insights/scorecard` says, pill and all,
 * and asks for the window the user picks.
 */

import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Scorecard as ScorecardData } from '../../api/scorecard'
import { Scorecard } from '../Scorecard'

const COUNTS = {
  total: 3,
  completed: 2,
  failed_platform: 1,
  failed_task: 0,
  failed_correct_refusal: 0,
  failed_unclassified: 0,
  cancelled: 0,
  completed_platform_failure_free: 1,
  platform_failure_free_rate: 1 / 3,
  platform_failure_free_rate_display: '33%',
}

const BODY: ScorecardData = {
  window: '7d',
  window_start: '2026-10-01T00:00:00+00:00',
  window_end: '2026-10-07T18:00:00+00:00',
  scope: 'Resume chains whose final run ended in the 7 UTC days to now.',
  counts: COUNTS,
  by_workflow: [],
  by_model: [],
  phases: [
    {
      phase_type: 'verify',
      phase_count: 4,
      median_tokens: 8_800_000,
      median_tokens_display: '8.8M',
      p90_tokens: 12_000_000,
      p90_tokens_display: '12.0M',
      cache_read_share: 0.9,
      cache_read_share_display: '90%',
      median_tool_calls: 41,
      median_tool_calls_display: '41.0',
      tokens_per_tool_call: 200_000,
      tokens_per_tool_call_display: '200.0k',
      phases_with_tool_counts: 4,
      median_cost_usd: '1.75',
      median_cost_display: '$1.75',
      p90_cost_usd: '4.20',
      p90_cost_display: '$4.20',
      phases_with_cost: 4,
    },
  ],
  phases_scope: 'Completed phases.',
  daily: [
    {
      day: '2026-10-07',
      counts: COUNTS,
      cost_usd: '9.50',
      cost_display: '$9.50',
      median_verify_tokens: 8_800_000,
      median_verify_tokens_display: '8.8M',
      median_verify_cost_usd: '1.75',
      median_verify_cost_display: '$1.75',
      peak_concurrency: 6,
      phases: [],
      by_workflow: [],
      by_model: [],
    },
  ],
  daily_scope: 'One point per UTC day.',
  throughput: {
    average_concurrency: 2.5,
    average_concurrency_display: '2.5',
    peak_concurrency: 6,
    median_queue_wait_seconds: 30,
    median_queue_wait_display: '30s',
    p90_queue_wait_seconds: 120,
    p90_queue_wait_display: '2m',
    queue_waits_measured: 3,
    scope: 'Every execution running in the window.',
  },
  total_cost_usd: '9.50',
  total_cost_display: '$9.50',
  cost_scope: 'Lane-2 cost of all 4 executions.',
  delivery: {
    merged_prs: null,
    cost_per_merged_pr_usd: null,
    cost_per_merged_pr_display: '—',
    scope: 'Not recorded: no event says which PR a run produced.',
  },
  targets: [
    {
      name: 'Median verify tokens',
      actual: 8_800_000,
      actual_display: '8.8M',
      target: 3_000_000,
      target_display: '≤ 3.0M',
      higher_is_better: false,
      status: 'off_track',
    },
    {
      name: 'Cost per merged PR (USD)',
      actual: null,
      actual_display: '—',
      target: 5,
      target_display: '≤ $5.00',
      higher_is_better: false,
      status: 'no_data',
    },
  ],
  eval_quality_scope: 'Not shown.',
}

describe('Scorecard', () => {
  afterEach(() => vi.restoreAllMocks())

  it('shows each target against its goal with its pill, and asks for the chosen window', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () =>
      new Response(JSON.stringify(BODY), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    )

    render(<Scorecard />)

    expect(await screen.findByText('Off track')).toBeTruthy()
    expect(screen.getByText('No data')).toBeTruthy()
    expect(screen.getByText('target ≤ 3.0M')).toBeTruthy()
    expect(screen.getByText('Failed: platform')).toBeTruthy()
    expect(screen.getByText('$1.75')).toBeTruthy()
    expect(screen.getByText('$4.20')).toBeTruthy()
    expect(screen.getByText('Not recorded: no event says which PR a run produced.')).toBeTruthy()
    expect(String(fetchMock.mock.calls[0][0])).toContain('/insights/scorecard?window=7d')

    fireEvent.click(screen.getByRole('button', { name: '30d' }))
    await screen.findAllByText('Off track')
    expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain('window=30d')
  })
})
