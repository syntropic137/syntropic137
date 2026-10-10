import { describe, expect, it } from 'vitest'
import { explorerColour, explorerModel, explorerStep, explorerX, type ExplorerVerifier } from './index'

// gen_trends.py EVAL_RUNS (sample) as series: the Landing board's explorer data.
const RUNS: [number, number, number, number | null][] = [
  [0, 0, 1.21, 82], [4, 0, 1.18, 85], [8, 0, 1.25, 61], [12, 0, 1.16, 84], [17, 0, 1.09, 88], [21, 0, 1.06, 90], [25, 0, 1.02, 91], [29, 0, 1.04, 92],
  [1, 1, 0.49, 48], [5, 1, 0.51, 55], [9, 1, 0.5, 72], [13, 1, 0.53, 63], [16, 1, 0.52, 66], [19, 1, 0.5, 78], [22, 1, 0.52, 84], [26, 1, 0.51, 87], [28, 1, 0.52, 89],
  [2, 2, 0.55, 80], [7, 2, 0.58, 78], [11, 2, 0.61, 64], [15, 2, 0.63, 76], [20, 2, 0.66, 62], [24, 2, 0.69, 73], [27, 2, 0.71, 58],
  [23, 3, 0.62, 79], [25, 3, 0.6, 66], [27, 3, 0.59, 81], [29, 3, 0.61, null],
]
const NAMES = ['claude-opus-5-5', 'claude-sonnet-5-5', 'gpt-5.6-sol', 'gpt-5.6-terra']
const VERIFIERS: ExplorerVerifier[] = NAMES.map((name, si) => {
  const runs = RUNS.filter((r) => r[1] === si).sort((a, b) => a[0] - b[0])
  return { name, days: runs.map((r) => r[0]), costs: runs.map((r) => r[2]), scores: runs.map((r) => r[3]) }
})

describe('eval explorer (Landing section 04)', () => {
  const m = explorerModel({ verifiers: VERIFIERS, passAt: 70, judge: 'claude-opus-5-5' })

  it('draws the board paths', () => {
    // svgpath(): x = (2 + d / 29 * 96) * 10, y = h - v / ymax * h, QH 230, CH 120, cost max 1.6.
    expect(explorerX(0, 29)).toBe(20)
    expect(explorerX(29, 29)).toBe(980)
    expect(m.costMax).toBe(1.6)
    expect(m.quality[0]!.d.startsWith('M20 41.4 L152.4 34.5')).toBe(true)
    expect(m.cost[0]!.d.startsWith('M20 29.3')).toBe(true)
    // The unscored last run of gpt-5.6-terra has a cost point but no quality point.
    expect(m.quality[3]!.d.split('L')).toHaveLength(3)
    expect(m.cost[3]!.d.split('L')).toHaveLength(4)
    expect(m.pass).toEqual({ y: 69, top: 0.30000000000000004, label: 'pass 70' })
    expect(m.qualityGrid).toEqual([0, 57.5, 115, 172.5, 230])
  })

  it('picks the best quality per dollar and writes its verdict', () => {
    expect(m.selected).toBe(1)
    expect(m.rows.map((r) => [r.rank, r.name, r.token])).toEqual([
      [1, 'claude-sonnet-5-5', '--sky-color-series-2'],
      [2, 'gpt-5.6-terra', '--sky-color-series-4'],
      [3, 'gpt-5.6-sol', '--sky-color-series-3'],
      [4, 'claude-opus-5-5', '--sky-color-series-1'],
    ])
    expect(m.verdict?.line).toBe('Up 29 points since its first runs, at the same cost.')
    expect(m.readout).toBe('/100 · $0.52 a run · +29 pts')
    const sol = explorerModel({ verifiers: VERIFIERS, selected: 2 })
    expect(sol.readout).toBe('/100 · $0.69 a run · −10 pts')
    expect(explorerModel({ verifiers: VERIFIERS, selected: 9 }).selected).toBe(1)
  })

  it('moves the selection in rank order with wrap', () => {
    expect(explorerStep(m.rows, 1, 1)).toBe(3)
    expect(explorerStep(m.rows, 1, -1)).toBe(0)
    expect(explorerStep(m.rows, 0, 1)).toBe(1)
    expect(explorerStep([], 2, 1)).toBe(2)
  })

  it('spreads runs without days and resolves colours', () => {
    const e = explorerModel({ verifiers: [{ name: 'x', scores: [50, 60, 70], costs: [0.1, 0.2, 0.3] }] })
    expect(e.quality[0]!.d).toBe('M20 115 L500 92 L980 69')
    expect(explorerColour(6, 0)).toBe('--sky-color-series-2')
    expect(explorerColour('--sky-harness-claude', 0)).toBe('--sky-harness-claude')
    expect(explorerModel({ verifiers: [] })).toMatchObject({ selected: 0, verdict: null, readout: '' })
  })
})
