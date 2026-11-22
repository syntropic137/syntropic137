/**
 * Firing history shows the cost the API rendered, verbatim (#897 slice J).
 *
 * The row used to format `cost_usd` itself as `$X.XXXX`, which turned unpriced
 * work into `$0.0000`. The API now sends `cost_display`, coverage included, and
 * the row must not re-derive it from `cost_usd`.
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { components } from '../../../generated/api-types'
import { TriggerFiringHistory } from '../TriggerFiringHistory'

type Entry = components['schemas']['TriggerHistoryEntryResponse']

function entry(overrides: Partial<Entry>): Entry {
  return {
    fired_at: '2026-11-22T09:00:00+00:00',
    execution_id: 'exec-a',
    webhook_delivery_id: '',
    event_type: 'check_run.completed',
    pr_number: 42,
    status: 'dispatched',
    cost_usd: null,
    cost_display: '—',
    unpriced_observation_count: 0,
    guard_name: '',
    block_reason: '',
    ...overrides,
  }
}

function costs(history: Entry[]): string[] {
  render(
    <MemoryRouter>
      <TriggerFiringHistory history={history} />
    </MemoryRouter>
  )
  return screen.getAllByTestId('firing-cost').map((el) => el.textContent ?? '')
}

describe('TriggerFiringHistory cost', () => {
  it('renders cost_display as the API sent it', () => {
    const shown = costs([
      entry({ execution_id: 'exec-a', cost_usd: 1.25, cost_display: '$1.25' }),
      entry({
        execution_id: 'exec-b',
        cost_usd: 0.4,
        cost_display: '>=$0.40 (partial)',
        unpriced_observation_count: 3,
      }),
      entry({ execution_id: 'exec-c', cost_usd: 0, cost_display: 'unpriced', unpriced_observation_count: 2 }),
      entry({ execution_id: '', status: 'blocked', cost_display: '—' }),
    ])

    expect(shown).toEqual(['$1.25', '>=$0.40 (partial)', 'unpriced', '—'])
  })

  it('does not format cost_usd itself', () => {
    costs([entry({ cost_usd: 0.123456, cost_display: '$0.12' })])

    expect(screen.queryByText('$0.1235')).toBeNull()
  })
})
