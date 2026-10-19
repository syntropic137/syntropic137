import { describe, expect, it } from 'vitest'
import { buildEvalTrendPrompt, evalTrendCommand } from '../../patterns/agentPrompt'
import { PASS_SCORE, changeNotes, compactTokens, evalTrendModel, minutesSeconds, parseTrendMetric, stepRun, trendReadout, verifierVerdict, type EvalTrendRowLike } from './trend'

const MODELS = ['claude-opus-5-5', 'claude-sonnet-5-5', 'gpt-5.6-sol', 'gpt-5.6-terra']
const RATE = [9, 3, 2.5, 2]
/** Eval board RAW: day, verifier, verdict, cost, seconds, score. */
const RAW: [number, number, string, number, number, number | null][] = [
  [0, 0, 'PASS', 1.21, 452, 82], [4, 0, 'PASS', 1.18, 431, 85], [8, 0, 'FAIL', 1.25, 470, 61], [12, 0, 'PASS', 1.16, 418, 84],
  [17, 0, 'PASS', 1.09, 392, 88], [21, 0, 'PASS', 1.06, 381, 90], [25, 0, 'PASS', 1.02, 366, 91], [29, 0, 'PASS', 1.04, 372, 92],
  [1, 1, 'FAIL', 0.49, 241, 48], [5, 1, 'FAIL', 0.51, 236, 55], [9, 1, 'PASS', 0.5, 247, 72], [13, 1, 'FAIL', 0.53, 252, 63],
  [16, 1, 'FAIL', 0.52, 240, 66], [19, 1, 'PASS', 0.5, 233, 78], [22, 1, 'PASS', 0.52, 238, 84], [26, 1, 'PASS', 0.51, 229, 87],
  [28, 1, 'PASS', 0.52, 245, 89], [2, 2, 'PASS', 0.55, 262, 80], [7, 2, 'PASS', 0.58, 255, 78], [11, 2, 'FAIL', 0.61, 249, 64],
  [15, 2, 'PASS', 0.63, 240, 76], [20, 2, 'FAIL', 0.66, 236, 62], [24, 2, 'PASS', 0.69, 231, 73], [27, 2, 'FAIL', 0.71, 228, 58],
  [23, 3, 'PASS', 0.62, 214, 79], [25, 3, 'FAIL', 0.6, 201, 66], [27, 3, 'PASS', 0.59, 196, 81], [29, 3, 'UNSCORED', 0.61, 190, null],
]
const DAY0 = Date.UTC(2026, 8, 8)
const ROWS: EvalTrendRowLike[] = RAW.map(([d, v, verdict, cost, secs, score]) => ({
  date: new Date(DAY0 + d * 86_400_000 + (9 + v * 2) * 3_600_000).toISOString(),
  verifier_model: MODELS[v]!,
  judge_model: score === null ? null : 'claude-opus-5-5',
  score,
  verdict: verdict === 'UNSCORED' ? null : verdict,
  cost_usd: String(cost),
  duration_seconds: secs,
  tokens: Math.round((cost / RATE[v]!) * 1e6),
  execution_id: `exec-${v}-${d}`,
}))
const CHANGES = [
  { definition_version: '1', changed_at: new Date(DAY0 - 2 * 86_400_000).toISOString(), kind: 'created' },
  { definition_version: '2', changed_at: new Date(DAY0 + 18 * 86_400_000).toISOString(), kind: 'updated' },
]

describe('eval trend model (Eval board sample)', () => {
  const m = evalTrendModel([...ROWS].reverse(), 'cost', CHANGES)

  it('summarises runs, verifiers and the judge', () => {
    expect(m.subtitle).toBe('28 runs in 30 days across 4 verifiers. Scores come from the judge model; a run passes at 70.')
    expect(m.judges).toBe('claude-opus-5-5')
    expect(m.series.map((s) => [s.short, s.color])).toEqual([['opus', 1], ['sonnet', 2], ['sol', 3], ['terra', 4]])
    expect(m.quality.pass).toBe(100 - PASS_SCORE)
  })

  it('writes the verifier cards like the board', () => {
    expect(m.cards.map((c) => [c.model, c.score, c.scoreDelta, c.metricValue, c.metricDelta, c.verdict])).toEqual([
      ['claude-opus-5-5', '91', '+14 since Sep 20', '$1.04', '−$0.16', 'Better and cheaper'],
      ['claude-sonnet-5-5', '87', '+24 since Sep 21', '$0.52', 'flat', 'Getting better'],
      ['gpt-5.6-sol', '64', '−10 since Sep 19', '$0.69', '+$0.11', 'Quality is slipping'],
      ['gpt-5.6-terra', '75', 'first runs', '$0.60', 'first runs', 'New verifier, not enough history'],
    ])
    expect(m.cards.map((c) => c.tone)).toEqual(['good', 'good', 'bad', 'neutral'])
  })

  it('switches the efficiency metric and its axis', () => {
    expect(m.efficiency.ticks.map((t) => t.label)).toEqual(['$0.00', '$0.40', '$0.80', '$1.20', '$1.60'])
    const speed = evalTrendModel(ROWS, 'speed')
    expect(speed.cards.map((c) => [c.metricValue, c.metricDelta])).toEqual([['6m 13s', '−1m 07s'], ['3m 57s', 'flat'], ['3m 52s', '−24s'], ['3m 16s', 'first runs']])
    expect(speed.efficiency.ticks.at(-1)!.label).toBe('8m')
    const tokens = evalTrendModel(ROWS, 'tokens')
    expect(tokens.cards.map((c) => c.metricValue)).toEqual(['116k', '172k', '275k', '300k'])
  })

  it('draws quality lines, dots and spread end labels', () => {
    expect(m.quality.dots).toHaveLength(27)
    expect(m.efficiency.dots).toHaveLength(28)
    expect(m.quality.lines[0]!.d.startsWith('M20 36')).toBe(true)
    const tops = m.quality.ends.map((e) => e.top)
    tops.slice(1).forEach((t, k) => expect(t - tops[k]!).toBeGreaterThanOrEqual(11 - 1e-9))
    expect(m.xTicks.map((t) => t.label)).toEqual(['Sep 8', 'Sep 15', 'Sep 22', 'Sep 29', 'Oct 6'])
  })

  it('marks the definition change and lays out verdict lanes', () => {
    expect(m.notes.map((n) => n.label)).toEqual(['Definition v2 · Sep 26'])
    expect(m.notes[0]!.x).toBeCloseTo(59.8, 0)
    expect(m.lanes.map((l) => l.ticks.length)).toEqual([8, 9, 7, 4])
    expect(m.lanes[3]!.ticks.at(-1)!.verdict).toBe('unscored')
  })

  it('reads out a run and steps through them in time order', () => {
    const r = trendReadout(m, m.initial)!
    expect(r).toMatchObject({ date: 'Oct 7, 2026', model: 'claude-opus-5-5', score: '92', scoreOf: 'of 100 · pass at 70', judge: 'claude-opus-5-5', cost: '$1.04', speed: '6m 12s', tokens: '116k', verdictWord: 'Pass' })
    const last = m.runs.length - 1
    expect(trendReadout(m, last)).toMatchObject({ model: 'gpt-5.6-terra', score: '—', scoreOf: 'not scored yet', judge: 'waiting for the scorer' })
    expect(stepRun(m, last, 1)).toBe(0)
    expect(stepRun(m, 0, -1)).toBe(last)
    expect(trendReadout(m, 99)).toBeNull()
  })

  it('handles no rows', () => {
    const e = evalTrendModel([], 'cost')
    expect(e.empty).toBe(true)
    expect(e.initial).toBe(-1)
    expect(stepRun(e, 0, 1)).toBe(-1)
  })
})

describe('eval trend helpers', () => {
  it('formats like the board', () => {
    expect(minutesSeconds(37)).toBe('37s')
    expect(minutesSeconds(372)).toBe('6m 12s')
    expect(compactTokens(134_444)).toBe('134k')
    expect(compactTokens(1_234_000)).toBe('1.23M')
    expect(parseTrendMetric('speed')).toBe('speed')
    expect(parseTrendMetric('nope')).toBe('cost')
  })

  it('gives each change its verdict', () => {
    expect(verifierVerdict({ fresh: false, q: 'up', e: 'up' })).toEqual({ text: 'Better, but costs more', tone: 'neutral' })
    expect(verifierVerdict({ fresh: false, q: 'flat', e: 'down' })).toEqual({ text: 'Same quality, cheaper', tone: 'good' })
    expect(verifierVerdict({ fresh: false, q: 'flat', e: 'up' })).toEqual({ text: 'Same quality, costs more', tone: 'bad' })
    expect(verifierVerdict({ fresh: false, q: 'flat', e: 'flat' })).toEqual({ text: 'Holding steady', tone: 'neutral' })
  })

  it('marks changes inside the span, never the creation', () => {
    const t0 = Date.parse('2026-09-01T00:00:00Z')
    const t1 = Date.parse('2026-09-11T00:00:00Z')
    const notes = changeNotes(
      [
        { definition_version: '1', changed_at: '2026-09-01T00:00:00Z', kind: 'created' },
        { definition_version: '1.4.0', changed_at: '2026-09-06T00:00:00Z', kind: 'phase_updated' },
        { definition_version: null, changed_at: '2026-09-08T00:00:00Z', kind: 'updated' },
        { definition_version: '3', changed_at: '2026-10-01T00:00:00Z', kind: 'updated' },
      ],
      t0,
      t1,
    )
    expect(notes.map((n) => n.label)).toEqual(['Definition 1.4.0 · Sep 6', 'Definition changed · Sep 8'])
    expect(notes[0]!.x).toBe(50)
  })

  it('shows "script" for a script-scored run, uses display strings, skips undated rows', () => {
    const rows = [
      { date: '2026-09-01T00:00:00Z', verifier_model: null, judge_model: null, score: 80, verdict: 'PASS', cost_usd: '0.5', cost_display: '≥ $0.50', duration_seconds: 61, duration_display: '1m 1s', tokens: 1000 },
      { date: null, verifier_model: 'a', score: 10, cost_usd: 1 },
    ]
    const mm = evalTrendModel(rows)
    expect(mm.runs).toHaveLength(1)
    expect(mm.judges).toBe('script')
    expect(trendReadout(mm, 0)).toMatchObject({ model: 'unknown model', judge: 'script', cost: '≥ $0.50', speed: '1m 1s' })
  })

  it('builds the agent prompt around the CLI command', () => {
    expect(evalTrendCommand('eval-x')).toBe('syn eval trend eval-x --json')
    const p = buildEvalTrendPrompt({ evalId: 'eval-x', evalName: 'case x' })
    expect(p).toContain('eval "case x" (eval-x)')
    expect(p).toContain('  syn eval trend eval-x --json')
    expect(p).toContain('score (0-100)')
  })
})
