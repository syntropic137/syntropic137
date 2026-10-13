import { describe, expect, it } from 'vitest'
import { rankVerdict, rankVerifiers, verdictLine, verifierStats, type RankVerifierInput } from './index'

// gen_trends.py EVAL_RUNS (sample): [day, series, cost, score]; the Landing board's explorer data.
const RUNS: [number, number, number, number | null][] = [
  [0, 0, 1.21, 82], [4, 0, 1.18, 85], [8, 0, 1.25, 61], [12, 0, 1.16, 84], [17, 0, 1.09, 88], [21, 0, 1.06, 90], [25, 0, 1.02, 91], [29, 0, 1.04, 92],
  [1, 1, 0.49, 48], [5, 1, 0.51, 55], [9, 1, 0.5, 72], [13, 1, 0.53, 63], [16, 1, 0.52, 66], [19, 1, 0.5, 78], [22, 1, 0.52, 84], [26, 1, 0.51, 87], [28, 1, 0.52, 89],
  [2, 2, 0.55, 80], [7, 2, 0.58, 78], [11, 2, 0.61, 64], [15, 2, 0.63, 76], [20, 2, 0.66, 62], [24, 2, 0.69, 73], [27, 2, 0.71, 58],
  [23, 3, 0.62, 79], [25, 3, 0.6, 66], [27, 3, 0.59, 81], [29, 3, 0.61, null],
]
const NAMES = ['claude-opus-5-5', 'claude-sonnet-5-5', 'gpt-5.6-sol', 'gpt-5.6-terra']
const VERIFIERS: RankVerifierInput[] = NAMES.map((name, si) => ({
  name,
  runs: RUNS.filter((r) => r[1] === si)
    .sort((a, b) => a[0] - b[0])
    .map(([, , costUsd, score]) => ({ costUsd, score })),
}))

describe('rankVerifiers (Landing explorer board)', () => {
  const ranking = rankVerifiers(VERIFIERS)

  it('matches the board numbers', () => {
    // EX in Landing.dc.html: score, cost, delta, per, runs, cd.
    const board = [
      [91, 1.04, 15, 87.5, 8, -0.1733],
      [87, 0.5167, 29, 168.387, 9, 0.0167],
      [64, 0.6867, -10, 93.204, 7, 0.1067],
      [75, 0.6, 0, 125, 4, -0.0033],
    ]
    ranking.stats.forEach((s, i) => {
      const [score, cost, delta, per, runs, cd] = board[i]!
      expect(s.score).toBe(score)
      expect(s.cost).toBeCloseTo(cost!, 3)
      expect(s.delta).toBe(delta)
      expect(s.per).toBeCloseTo(per!, 2)
      expect(s.runs).toBe(runs)
      expect(s.costDelta).toBeCloseTo(cd!, 3)
    })
    expect(ranking.best).toBe(1)
  })

  it('ranks by quality per dollar with the board words', () => {
    expect(ranking.rows.map((r) => [r.rank, r.name, r.score, r.cost, r.per, r.word, r.tone, r.bestText])).toEqual([
      [1, 'claude-sonnet-5-5', '87', '$0.52', '168 pts/$', 'Improving', 'good', 'Best quality per dollar'],
      [2, 'gpt-5.6-terra', '75', '$0.60', '125 pts/$', 'New', 'neutral', ''],
      [3, 'gpt-5.6-sol', '64', '$0.69', '93 pts/$', 'Slipping', 'bad', ''],
      [4, 'claude-opus-5-5', '91', '$1.04', '88 pts/$', 'Improving', 'good', ''],
    ])
  })

  it('writes the one-line verdict', () => {
    const lines = ranking.stats.map(verdictLine)
    expect(lines).toEqual([
      'Up 15 points since its first runs, and $0.17 cheaper per run.',
      'Up 29 points since its first runs, at the same cost.',
      'Down 10 points since its first runs, while costing $0.11 more per run.',
      'Only 4 runs so far. Give it a week before trusting the trend.',
    ])
    for (const l of lines) expect(l).not.toMatch(/—/)
    expect(rankVerdict(ranking.stats[2]!)).toEqual({
      index: 2,
      name: 'gpt-5.6-sol',
      score: '64',
      cost: '$0.69',
      delta: '−10 pts',
      line: 'Down 10 points since its first runs, while costing $0.11 more per run.',
    })
  })

  it('handles a lone run and no scores', () => {
    const s = verifierStats({ name: 'x', runs: [{ costUsd: 0.4, score: null }] }, 0)
    expect(s).toMatchObject({ score: null, per: null, fresh: true })
    expect(verdictLine(s)).toBe('Only 1 run so far. Give it a week before trusting the trend.')
    const r = rankVerifiers([{ name: 'x', runs: [] }])
    expect(r.best).toBeNull()
    expect(r.rows[0]).toMatchObject({ score: '—', per: '—' })
  })
})
