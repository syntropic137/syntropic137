/**
 * The heatmap shows the cost the API rendered, verbatim (#897).
 *
 * It used to format `breakdown.cost_usd` itself with `toFixed(2)`, so a day or a
 * window with unpriced model groups read as a complete dollar figure. The
 * fixtures carry `cost_usd` values that cannot format to the displays, so a
 * surface that formats the dollars itself again cannot pass.
 */

import { render, screen, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { components } from '../../../generated/api-types'
import { ContributionHeatmap } from '../ContributionHeatmap'

type Bucket = components['schemas']['HeatmapDayBucketResponse']
type Heatmap = components['schemas']['ContributionHeatmapResponse']

function bucket(date: string, cost_usd: number, unpriced_tokens: number, cost_display: string): Bucket {
  return {
    date,
    count: 1,
    breakdown: {
      sessions: 1,
      executions: 1,
      commits: 0,
      cost_usd,
      tokens: 300,
      input_tokens: 100,
      output_tokens: 200,
      cache_creation_tokens: 0,
      cache_read_tokens: 0,
      failed: 0,
      unpriced_tokens,
    },
    cost_display,
    failed: 0,
  }
}

// As the API renders them: format_cost goes incomplete whenever unpriced_tokens > 0.
const HEATMAP: Heatmap = {
  metric: 'sessions',
  start_date: '2026-11-01',
  end_date: '2026-11-03',
  total: 3,
  total_cost_display: '>=$1.75 (partial)',
  days: [
    bucket('2026-11-01', 1.25, 0, '$1.25'),
    bucket('2026-11-02', 0.5, 1_700, '>=$0.50 (partial)'),
    bucket('2026-11-03', 0, 40, 'unpriced'),
  ],
  filter: {},
}

vi.mock('../../../api/base', () => ({
  API_BASE: '/api/v1',
  fetchJSON: () => Promise.resolve(HEATMAP),
}))

// nivo only draws a tooltip on hover in a measured SVG; render each day's directly.
vi.mock('@nivo/calendar', () => ({
  ResponsiveCalendar: ({ data, tooltip }: {
    data: { day: string }[]
    tooltip: (p: { day: string }) => ReactNode
  }) => (
    <div>
      {data.map((d) => (
        <div key={d.day} data-testid={`tooltip-${d.day}`}>{tooltip({ day: d.day })}</div>
      ))}
    </div>
  ),
}))

describe('ContributionHeatmap cost', () => {
  it('shows the window total the API rendered', async () => {
    render(<ContributionHeatmap />)

    const label = await screen.findByText('Total cost')
    expect(label.parentElement).toHaveTextContent('>=$1.75 (partial)')
    expect(screen.queryByText('$1.75')).toBeNull()
  })

  it.each([
    ['2026-11-01', '$1.25'],
    ['2026-11-02', '>=$0.50 (partial)'],
    ['2026-11-03', 'unpriced'],
  ])('shows the cost the API rendered for %s', async (day, shows) => {
    render(<ContributionHeatmap />)

    const tooltip = await screen.findByTestId(`tooltip-${day}`)
    expect(within(tooltip).getByText(shows)).toBeInTheDocument()
  })

  it('never formats the unpriced day as dollars', async () => {
    render(<ContributionHeatmap />)

    const tooltip = await screen.findByTestId('tooltip-2026-11-03')
    expect(tooltip).not.toHaveTextContent('$0.00')
  })
})
