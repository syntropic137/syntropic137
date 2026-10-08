import { describe, expect, it } from 'vitest'

import { runsSubtitle } from '../evalSummary'

describe('runsSubtitle', () => {
  it('says "all" when there are no runs or they fit on one page', () => {
    expect(runsSubtitle({ page: 1, pageSize: 50, total: 0 })).toBe('All 0 runs, newest first')
    expect(runsSubtitle({ page: 1, pageSize: 50, total: 50 })).toBe('All 50 runs, newest first')
  })

  it('names the slice of a full first page and of a partial last page', () => {
    expect(runsSubtitle({ page: 1, pageSize: 50, total: 120 })).toBe('Runs 1–50 of 120, newest first')
    expect(runsSubtitle({ page: 3, pageSize: 50, total: 120 })).toBe('Runs 101–120 of 120, newest first')
  })
})
