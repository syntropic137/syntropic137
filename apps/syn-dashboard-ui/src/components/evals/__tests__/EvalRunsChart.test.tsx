import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { evalRun } from '../../../test/evalFixtures'
import { VERDICT_COLOURS, UNSCORED_COLOUR } from '../../../utils/evalVerdict'
import { EvalRunsChart } from '../EvalRunsChart'

function markers(container: HTMLElement) {
  return [...container.querySelectorAll('circle')]
}

describe('EvalRunsChart', () => {
  it('says there are no runs instead of drawing an empty axis', () => {
    const { container } = render(<EvalRunsChart runs={[]} />)
    expect(screen.getByText(/No runs yet/)).toBeInTheDocument()
    expect(container.querySelector('svg')).toBeNull()
  })

  it('centres a single run rather than dividing by a zero time span', () => {
    const { container } = render(<EvalRunsChart runs={[evalRun()]} />)
    const [only] = markers(container)
    expect(only.getAttribute('cx')).toBe('300')
  })

  it('colours each marker by its verdict, with unscored runs apart from all three', () => {
    const runs = [
      evalRun({ execution_id: 'a', started_at: '2026-10-01T00:00:00Z', verdict: 'PASS' }),
      evalRun({ execution_id: 'b', started_at: '2026-10-02T00:00:00Z', verdict: 'FAIL' }),
      evalRun({ execution_id: 'c', started_at: '2026-10-03T00:00:00Z', verdict: 'ERROR' }),
      evalRun({ execution_id: 'd', started_at: '2026-10-04T00:00:00Z', verdict: null }),
    ]
    const { container } = render(<EvalRunsChart runs={runs} />)
    const fills = Object.fromEntries(markers(container).map((c) => [c.dataset.verdict, c.getAttribute('fill')]))
    expect(fills).toEqual({
      PASS: VERDICT_COLOURS.PASS,
      FAIL: VERDICT_COLOURS.FAIL,
      ERROR: VERDICT_COLOURS.ERROR,
      UNSCORED: UNSCORED_COLOUR,
    })
    expect(new Set(Object.values(fills)).size).toBe(4)
  })

  it('places runs in time order and puts each variant in its own lane', () => {
    const runs = [
      evalRun({ execution_id: 'late', started_at: '2026-10-05T00:00:00Z' }),
      evalRun({ execution_id: 'early', started_at: '2026-10-01T00:00:00Z' }),
      evalRun({
        execution_id: 'other-model',
        started_at: '2026-10-03T00:00:00Z',
        models: [{ phase_id: 'implement', model: 'gpt-6' }],
      }),
    ]
    const { container } = render(<EvalRunsChart runs={runs} />)
    expect(container.querySelectorAll('[data-lane]')).toHaveLength(2)
    const byId = Object.fromEntries(
      markers(container).map((c) => [c.querySelector('title')?.textContent?.split(' · ')[2], c]),
    )
    expect(Number(byId.early.getAttribute('cx'))).toBeLessThan(Number(byId.late.getAttribute('cx')))
    expect(byId.early.getAttribute('cy')).toBe(byId.late.getAttribute('cy'))
    expect(byId['other-model'].getAttribute('cy')).not.toBe(byId.late.getAttribute('cy'))
  })
})
