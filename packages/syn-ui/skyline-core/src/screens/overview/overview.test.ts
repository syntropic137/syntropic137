import { describe, expect, it } from 'vitest'
import {
  activeDayCount,
  attentionRuns,
  countWord,
  distinctRepoCount,
  heatmapToSkylineDays,
  outcomeCounts,
  outcomeLine,
  overviewHeadline,
  runningCount,
  skylineYears,
  tokenMix,
  topWorkflows,
  triggerLine,
} from './index'

describe('heatmapToSkylineDays', () => {
  it('maps the breakdown and sorts by date', () => {
    const days = heatmapToSkylineDays([
      { date: '2026-08-28', count: 43, breakdown: { sessions: 43, executions: 23, commits: 0, cost_usd: 4.9849, input_tokens: 1, output_tokens: 2, cache_creation_tokens: 3, cache_read_tokens: 4 } },
      { date: '2026-07-25T00:00:00Z', count: 8 },
    ])
    expect(days.map((d) => d.date)).toEqual(['2026-07-25', '2026-08-28'])
    expect(days[0]).toMatchObject({ sessions: 8, executions: 0, costUsd: null, tokens: null })
    expect(days[1]).toMatchObject({ sessions: 43, executions: 23, costUsd: 4.9849, tokens: { input: 1, output: 2, cacheWrite: 3, cacheRead: 4 } })
  })
  it('treats all-zero tokens as unknown and handles null input', () => {
    expect(heatmapToSkylineDays([{ date: '2026-08-06', breakdown: { sessions: 1, input_tokens: 0 } }])[0]!.tokens).toBeNull()
    expect(heatmapToSkylineDays(undefined)).toEqual([])
  })
})

describe('active days and years', () => {
  const days = heatmapToSkylineDays([
    { date: '2025-12-30', count: 2 },
    { date: '2026-01-02', count: 0 },
    { date: '2026-03-02', count: 5 },
  ])
  it('counts days with sessions', () => expect(activeDayCount(days)).toBe(2))
  it('lists years with activity plus the current one', () => {
    expect(skylineYears(days, 2026)).toEqual([2025, 2026])
    expect(skylineYears([], 2026)).toEqual([2026])
  })
})

describe('headline', () => {
  it('reads like the board', () => {
    expect(overviewHeadline({ running: 0, needsLook: 2 })).toEqual({ lead: 'All quiet.', follow: 'Two runs need a look.' })
    expect(overviewHeadline({ running: 1, needsLook: 1 })).toEqual({ lead: 'One run working.', follow: 'One run needs a look.' })
    expect(overviewHeadline({ running: 3, needsLook: 0 }).follow).toBe('Nothing needs a look.')
  })
  it('spells small numbers only', () => {
    expect(countWord(0)).toBe('No')
    expect(countWord(12)).toBe('12')
  })
})

describe('runs', () => {
  const runs = [
    { workflow_execution_id: 'a', workflow_name: 'A', status: 'failed' },
    { workflow_execution_id: 'b', workflow_name: 'B', status: 'running' },
    { workflow_execution_id: 'c', workflow_name: 'C', status: 'completed' },
    { workflow_execution_id: 'd', workflow_name: 'D', status: 'failed' },
    { workflow_execution_id: 'e', workflow_name: 'E', status: 'failed' },
  ]
  it('picks failed runs for attention', () => expect(attentionRuns(runs).map((r) => r.workflow_execution_id)).toEqual(['a', 'd']))
  it('counts running', () => expect(runningCount(runs)).toBe(1))
})

describe('outcomes', () => {
  it('folds interrupted into cancelled', () => {
    expect(outcomeCounts({ completed: 50, failed: 23, cancelled: 1, interrupted: 1 })).toEqual({ completed: 50, failed: 23, cancelled: 2 })
    expect(outcomeCounts(undefined)).toEqual({ completed: 0, failed: 0, cancelled: 0 })
  })
  it('writes the line', () => {
    expect(outcomeLine({ completed: 50, failed: 23, cancelled: 2 })).toBe('50 completed · 23 failed · 2 cancelled')
    expect(outcomeLine({ completed: 50, failed: 0, cancelled: 2 }, true)).toBe('50 done · 2 cancelled')
    expect(outcomeLine({ completed: 0, failed: 0, cancelled: 0 })).toBe('none yet')
  })
})

describe('tokenMix', () => {
  it('splits the four series with shares', () => {
    const mix = tokenMix({ total_input_tokens: 726_900, total_output_tokens: 202_800, total_cache_creation_tokens: 0, total_cache_read_tokens: 9_300_000 })
    expect(mix.total).toBe(10_229_700)
    expect(mix.parts.map((p) => p.key)).toEqual(['cacheRead', 'output', 'input'])
    expect(mix.parts[0]!.share).toBe('90.9%')
    expect(mix.parts[0]!.display).toBe('9.30M')
  })
  it('is empty with no tokens', () => expect(tokenMix(null)).toEqual({ total: 0, parts: [] }))
})

describe('topWorkflows', () => {
  it('sorts by runs and scales to the busiest', () => {
    const top = topWorkflows([
      { id: '1', name: 'Research', runs_count: 12 },
      { id: '2', name: 'Codex', runs_count: 26 },
      { id: '3', name: 'Never', runs_count: 0 },
      { id: '4', name: 'Once', runs_count: 1 },
    ])
    expect(top.map((w) => w.id)).toEqual(['2', '1', '4'])
    expect(top[0]).toMatchObject({ runs: '26 runs', percent: 100 })
    expect(top[1]!.percent).toBe(46)
    expect(top[2]).toMatchObject({ runs: '1 run', percent: 4 })
  })
})

describe('triggers', () => {
  it('counts repos and writes the line', () => {
    expect(distinctRepoCount([{ repository: 'a/b' }, { repository: 'a/b' }, { repository: 'c/d' }, { repository: null }])).toBe(2)
    expect(triggerLine(2)).toBe('watching GitHub events on 2 repos')
    expect(triggerLine(1, true)).toBe('watching 1 repo')
    expect(triggerLine(0)).toBe('nothing watching yet')
  })
})
