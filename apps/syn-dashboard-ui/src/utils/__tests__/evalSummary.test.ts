import { describe, expect, it } from 'vitest'

import { stats } from '../../test/evalFixtures'
import { judgedCount, runsSubtitle, verdictBreakdown } from '../evalSummary'

describe('verdictBreakdown', () => {
  it('names every population separately, ERROR and unscored included', () => {
    const s = stats({ pass_count: 2, fail_count: 3, error_count: 1, unscored_count: 6 })
    expect(verdictBreakdown(s)).toBe('2 PASS · 3 FAIL · 1 ERROR · 6 unscored')
  })
})

describe('judgedCount', () => {
  it('is PASS + FAIL only: an ERROR or unscored run is not a judgement', () => {
    expect(judgedCount(stats({ pass_count: 1, fail_count: 2, error_count: 7, unscored_count: 9 }))).toBe(3)
  })
})

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
