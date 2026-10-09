import { describe, expect, it } from 'vitest'
import { median, parsePerfMetric, perfReadout, perfRuns, phaseDurationGraphs, stepPerfRun, workflowPerformance, type PerfRowLike } from './performance'

// The Workflow board's Performance sample: [day, status, cost, seconds, phase seconds].
const RAW: [number, string, number, number, number[]][] = [
  [0, 'completed', 0.162, 418, [96, 188, 134]],
  [3, 'completed', 0.151, 402, [92, 181, 129]],
  [6, 'failed', 0.071, 196, [88, 108, 0]],
  [9, 'completed', 0.148, 389, [90, 172, 127]],
  [12, 'completed', 0.139, 371, [84, 166, 121]],
  [15, 'cancelled', 0.044, 120, [80, 40, 0]],
  [18, 'completed', 0.124, 333, [71, 150, 112]],
  [21, 'completed', 0.118, 318, [66, 146, 106]],
  [25, 'completed', 0.113, 301, [62, 139, 100]],
  [28, 'completed', 0.109, 289, [58, 134, 97]],
  [31, 'completed', 0.106, 276, [55, 128, 93]],
  [34, 'completed', 0.104, 266, [52, 124, 90]],
]
const DAY0 = Date.parse('2026-09-01T00:00:00Z')
const PH = ['Discovery Phase', 'Deep Dive Analysis', 'Synthesis & Documentation']
const ROWS: PerfRowLike[] = RAW.map(([d, status, cost, secs, ph], i) => ({
  execution_id: `exec-${i}`,
  date: new Date(DAY0 + d * 86_400_000).toISOString(),
  status,
  cost_usd: String(cost),
  duration_seconds: secs,
  tokens: Math.round(cost / 0.5e-6),
  phase_durations: ph.map((s, k) => ({ phase_id: `p${k}`, phase_name: PH[k]!, duration_seconds: s || null })),
})).reverse()

describe('workflow performance (Workflow board sample)', () => {
  it('orders runs oldest first and keeps a rolling success share', () => {
    const runs = perfRuns(ROWS)
    expect(runs.map((r) => r.executionId)[0]).toBe('exec-0')
    expect(runs.map((r) => r.ok)).toEqual([100, 100, 67, 75, 80, 60, 60, 80, 80, 80, 100, 100])
    expect(runs.filter((r) => r.counted)).toHaveLength(10)
    expect(runs[0]!.x).toBe(2)
    expect(runs.at(-1)!.x).toBe(98)
  })

  it('reads the four summary cards like the board', () => {
    const m = workflowPerformance(ROWS, 'cost')
    expect(m.kpis.map((k) => [k.label, k.value, k.word, k.delta])).toEqual([
      ['Success, last 5', '100%', 'Improving', '+20 pts vs first 5 runs'],
      ['Median duration', '4m 36s', 'Improving', '−2m 06s vs first runs'],
      ['Cost per run', '$0.106', 'Improving', '−$0.047 vs first runs'],
      ['Tokens per run', '213k', 'Improving', '−95k vs first runs'],
    ])
  })

  it('draws completed runs on the line and the rest on the baseline', () => {
    const m = workflowPerformance(ROWS, 'cost')
    expect(m.subtitle).toBe('12 runs over 5 weeks. Lower is better. Failed and cancelled runs sit on the baseline and are not counted.')
    expect(m.yTicks.map((t) => t.label)).toEqual(['$0.00', '$0.05', '$0.10', '$0.15', '$0.20'])
    const failed = m.dots[2]!
    expect(failed).toMatchObject({ tone: 'failed', muted: true, top: 100 })
    expect(failed.label).toBe('Sep 7: Failed, not counted')
    expect(m.dots[0]).toMatchObject({ tone: 'completed', muted: false })
    expect(m.lines[0]!.d.split('L')).toHaveLength(10)
    expect(m.ends[0]!.label).toBe('$0.104')
    const s = workflowPerformance(ROWS, 'success')
    expect(s.subtitle.endsWith('Higher is better.')).toBe(true)
    expect(s.dots.every((d) => !d.muted)).toBe(true)
    expect(workflowPerformance(ROWS, 'speed').yTicks.at(-1)!.label).toBe('8m')
  })

  it('marks definition changes inside the span', () => {
    const m = workflowPerformance(ROWS, 'cost', [
      { definition_version: '1', changed_at: '2026-07-01T00:00:00Z', kind: 'created' },
      { definition_version: '2', changed_at: new Date(DAY0 + 16 * 86_400_000).toISOString(), kind: 'updated' },
    ])
    expect(m.notes.map((n) => n.label)).toEqual(['Definition v2 · Sep 17'])
  })

  it('graphs each phase over completed runs', () => {
    const g = phaseDurationGraphs(perfRuns(ROWS))
    expect(g.map((p) => [p.name, p.now, p.delta, p.tone])).toEqual([
      ['Discovery Phase', '55s', '−40% vs first runs', 'good'],
      ['Deep Dive Analysis', '2m 08s', '−29% vs first runs', 'good'],
      ['Synthesis & Documentation', '1m 33s', '−28% vs first runs', 'good'],
    ])
    expect(g[0]!.label).toBe('Discovery Phase: median 55s, 40% faster')
  })

  it('reads out and steps through runs', () => {
    const m = workflowPerformance(ROWS)
    expect(m.initial).toBe(11)
    expect(perfReadout(m, 11)).toMatchObject({ date: 'Oct 5, 2026', statusWord: 'Completed', speed: '4m 26s', cost: '$0.104', success: '100%', executionId: 'exec-11' })
    expect(stepPerfRun(m, 11, 1)).toBe(0)
    expect(stepPerfRun(m, 0, -1)).toBe(11)
    expect(perfReadout(m, 99)).toBeNull()
  })

  it('handles no runs, undated rows and few runs', () => {
    expect(workflowPerformance([]).empty).toBe(true)
    expect(workflowPerformance([{ ...ROWS[0]!, date: null }]).empty).toBe(true)
    const few = workflowPerformance(ROWS.slice(0, 2))
    expect(few.kpis.every((k) => k.delta === 'first runs' && k.word === 'Flat')).toBe(true)
    expect(phaseDurationGraphs(perfRuns(ROWS.slice(0, 2)))[0]!.delta).toBe('first runs')
  })

  it('parses the metric and takes medians', () => {
    expect(parsePerfMetric('speed')).toBe('speed')
    expect(parsePerfMetric(null)).toBe('cost')
    expect(median([3, 1, 2])).toBe(2)
    expect(median([4, 1, 2, 3])).toBe(2.5)
    expect(median([])).toBe(0)
  })
})
