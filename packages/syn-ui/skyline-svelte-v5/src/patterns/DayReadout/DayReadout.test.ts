// @vitest-environment jsdom
// Day Readout names a UTC day (#1939 interim): the Skyline buckets by utc_day(time), and the Runs link
// lands on /executions?day=, whose chip already reads "Started <day> UTC" (#1940).
import '../../components/_test/setup'
import { render } from '@testing-library/svelte'
import { describe, expect, it } from 'vitest'
import DayReadout from './DayReadout.svelte'

const day = { date: '2026-10-14', sessions: 3, executions: 2 }
const dateText = (c: HTMLElement) => c.querySelector('.sky-readout__date')?.textContent

describe('DayReadout', () => {
  it('labels the phone day card as a UTC day', () => {
    const { container } = render(DayReadout, { day, variant: 'card', runsHref: '/executions?day=2026-10-14' })
    expect(dateText(container)).toBe('Wed, Oct 14 (UTC)')
  })

  it('labels the desktop dock as a UTC day, after the year', () => {
    const { container } = render(DayReadout, { day, variant: 'dock', runsHref: '/executions?day=2026-10-14' })
    expect(dateText(container)).toBe('Wed, Oct 14, 2026 (UTC)')
  })
})
