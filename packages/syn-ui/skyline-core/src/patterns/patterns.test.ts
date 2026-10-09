import { describe, expect, it } from 'vitest'
import {
  ABSENCE_TEXT,
  buildAgentPrompt,
  buildRuleClauses,
  cellKey,
  dayReadout,
  foldOutput,
  normalizeVerdict,
  operationStatusText,
  operationsToText,
  operatorWords,
  phaseKitChips,
  phaseKitLine,
  provenanceSummary,
  ruleText,
  runBarColumns,
  runBarPercent,
  runSegments,
  runSlots,
  runSubline,
  shortDigest,
  skillRefDisplay,
  toolGlyph,
  usageModel,
  verdictCellLabel,
  verifierFooter,
  GLYPH,
  STATUS_GLYPH_PATHS,
  type VerdictCell,
} from './index'

describe('run row', () => {
  it('colours phase blocks by where the run stopped', () => {
    expect(runSegments({ status: 'completed', done: 3, total: 3 })).toEqual(['done', 'done', 'done'])
    expect(runSegments({ status: 'failed', done: 0, total: 2 })).toEqual(['failed', 'empty'])
    expect(runSegments({ status: 'cancelled', done: 2, total: 3 })).toEqual(['done', 'done', 'cancelled'])
    expect(runSegments({ status: 'running', done: 1, total: 3 })).toEqual(['done', 'running', 'empty'])
    expect(runSegments({ status: 'completed', done: 9, total: 1 })).toEqual(['done'])
  })
  it('scales the bar against the longest run', () => {
    expect(runBarPercent(227_000, 227_000)).toBe(100)
    expect(runBarPercent(62_000, 227_000)).toBe(27)
    expect(runBarPercent(5_000, 227_000)).toBe(4)
    expect(runBarPercent(null, 227_000)).toBe(4)
  })
  it('shares one phase grid across a list so blocks line up (feedback c80ad278)', () => {
    expect(runSlots([8, 3, null, 10, 0])).toBe(10)
    expect(runSlots([])).toBe(1)
    expect(runSlots([undefined])).toBe(1)
    // A 1-minute 8-phase run gets the same column width as a 2-hour one: the
    // grid depends on the list's slots, never on duration.
    expect(runBarColumns(8, 10)).toBe(10)
    expect(runBarColumns(3, 10)).toBe(10)
    // A row with more phases than the list declared widens its own grid.
    expect(runBarColumns(12, 10)).toBe(12)
    expect(runBarColumns(4, undefined)).toBe(4)
    expect(runBarColumns(0, 0)).toBe(1)
  })
  it('writes the sub line', () => {
    expect(runSubline('syntropic137/syntropic137', 0, 2)).toBe('syntropic137/syntropic137 · 0 of 2 phases')
    expect(runSubline('', 1, 1)).toBe('no repo · 1 of 1 phase')
    expect(runSubline(null, 3, 3, true)).toBe('no repo · 3/3 phases')
  })
  it('has a glyph for every status', () => {
    expect(STATUS_GLYPH_PATHS.check).toBe(GLYPH.check)
    expect(Object.keys(STATUS_GLYPH_PATHS)).toHaveLength(8)
  })
})

describe('dayReadout', () => {
  it('formats the board day', () => {
    const r = dayReadout({
      date: '2026-08-28',
      sessions: 43,
      executions: 23,
      commits: 0,
      costUsd: 4.9849,
      tokens: { input: 464_027, output: 137_651, cacheWrite: 517_201, cacheRead: 4_556_030 },
    })
    expect(r.dateLabel).toBe('Fri, Aug 28')
    expect(r.year).toBe('2026')
    expect([r.sessions, r.executions, r.commits]).toEqual(['43', '23', '0'])
    expect(r.tokens).toBe('5.67M')
    expect(r.cost).toBe('$4.98')
    expect(r.parts.map((p) => [p.label, p.display])).toEqual([
      ['Cache read', '4.56M'],
      ['Cache write', '517.2K'],
      ['Output', '137.7K'],
      ['Input', '464.0K'],
    ])
    expect(r.hasTokens).toBe(true)
  })
  it('handles a day without tokens or cost', () => {
    const r = dayReadout({ date: '2026-08-06', sessions: 1 })
    expect(r.hasTokens).toBe(false)
    expect(r.tokens).toBe('0')
    expect(r.cost).toBe('—')
    expect(r.parts.every((p) => p.flex === 0)).toBe(true)
  })
})

describe('usageModel', () => {
  it('matches the execution meter, cost by phase', () => {
    const m = usageModel({
      tokens: { cacheRead: 313_560, cacheWrite: 64_884, output: 18_254, input: 93 },
      costBy: 'phase',
      costRows: [
        { label: '01 Discovery', value: 0.0557 },
        { label: '02 Deep Dive', value: 0.0798 },
        { label: '03 Synthesis', value: 0.0745 },
      ],
    })
    expect(m.cost).toBe('$0.2100')
    expect(m.tokensLabel).toBe('396.8K tokens')
    expect(m.series.map((s) => [s.label, s.display, s.percent])).toEqual([
      ['Cache read', '313,560', '79.0%'],
      ['Cache write', '64,884', '16.4%'],
      ['Output', '18,254', '4.6%'],
      ['Input', '93', '0.0%'],
    ])
    expect(m.costRows.map((r) => [r.display, r.percent, r.fill, r.tone])).toEqual([
      ['$0.0557', '27%', 70, 'accent'],
      ['$0.0798', '38%', 100, 'accent'],
      ['$0.0745', '35%', 93, 'accent'],
    ])
    expect(m.bandLabel).toBe('Tokens by type: Cache read 79.0 percent, Cache write 16.4 percent, Output 4.6 percent, Input 0.0 percent')
  })
  it('matches the session meter, cost by model, with a rate badge', () => {
    const m = usageModel({
      cost: '$0.2162',
      tokens: { cacheRead: 144_128, cacheWrite: 0, output: 1_945, input: 29_924 },
      costBy: 'model',
      rates: { cacheRead: '0.1× rate' },
      costRows: [{ label: 'gpt-5.6-sol', value: 0.2162 }],
    })
    expect(m.cost).toBe('$0.2162')
    expect(m.series.map((s) => s.key)).toEqual(['cacheRead', 'output', 'input'])
    expect(m.series[0]!.rate).toBe('0.1× rate')
    expect(m.costRows[0]).toMatchObject({ percent: '100%', fill: 100, tone: 'neutral' })
  })
  it('reads empty usage', () => {
    const m = usageModel({ tokens: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, costBy: 'model', costRows: [{ label: 'x', value: null }] })
    expect(m.bandLabel).toBe('No tokens recorded')
    expect(m.costRows[0]).toMatchObject({ display: '—', percent: '—', fill: 0 })
  })
})

describe('verdicts', () => {
  it('normalises API verdicts', () => {
    expect(normalizeVerdict('PASS')).toBe('pass')
    expect(normalizeVerdict('failed')).toBe('fail')
    expect(normalizeVerdict('scorer_error')).toBe('error')
    expect(normalizeVerdict(null)).toBe('unscored')
    expect(normalizeVerdict(true)).toBe('pass')
  })
  it('summarises a verifier column like the board footer', () => {
    const col: VerdictCell[] = [
      { verdict: 'fail', costUsd: 0.66, durationMs: 228_000 },
      { verdict: 'pass', costUsd: 0.59, durationMs: 204_000 },
      { verdict: 'fail', costUsd: 0.71, durationMs: 246_000 },
      { verdict: 'pass', costUsd: 0.49, durationMs: 187_000 },
      { verdict: 'fail', costUsd: 0.63, durationMs: 219_000 },
      { verdict: 'error', costUsd: 0.6, durationMs: 231_000 },
    ]
    const f = verifierFooter(col)
    expect(f.fraction).toBe('2/6')
    expect(f.fill).toBe(33)
    expect(f.note).toBe('caught · 1 scorer error')
    expect(f.averages).toBe('$0.61 · 3m 39s')
    const none = verifierFooter([{ verdict: 'unscored' }, undefined])
    expect(none).toMatchObject({ fraction: '—', scored: false, note: 'not scored yet', averages: '— · —' })
  })
  it('labels cells', () => {
    const c = { id: 'c1', name: 'codex-cost-limit' }
    const v = { id: 'v3', agent: 'Codex', model: 'gpt-5.6-sol' }
    expect(verdictCellLabel(c, v, { verdict: 'pass', costUsd: 0.49 })).toBe('codex-cost-limit under gpt-5.6-sol: Pass, $0.49')
    expect(verdictCellLabel(c, v, { verdict: 'error' })).toBe('codex-cost-limit under gpt-5.6-sol: Scorer error')
    expect(verdictCellLabel(c, v, undefined)).toBe('codex-cost-limit under gpt-5.6-sol: no run')
    expect(cellKey('a', 'b')).toBe('a:b')
  })
})

describe('phase kit and skill refs', () => {
  it('shortens digests and shas but keeps branches', () => {
    expect(shortDigest('sha256:db8ee61f00aa')).toBe('sha256:db8ee61')
    expect(shortDigest('sha256-db8ee61f00aa')).toBe('sha256-db8ee61')
    expect(shortDigest('3b3fad96af16a10759d930941b4520ba0c40edae')).toBe('3b3fad9')
    expect(shortDigest('main')).toBe('main')
    expect(shortDigest(null)).toBeNull()
  })
  it('builds the skill ref display', () => {
    const d = skillRefDisplay({
      name: 'doc-coauthoring',
      source: 'anthropics/skills',
      ref: '3b3fad96af16a10759d930941b4520ba0c40edae',
      href: 'https://github.com/anthropics/skills/tree/3b3fad96af16a10759d930941b4520ba0c40edae',
    })
    expect(d.ref).toBe('3b3fad9')
    expect(d.linkLabel).toBe('Source of doc-coauthoring at 3b3fad9')
    expect(skillRefDisplay({ name: 'x', source: './x' }).linkLabel).toBeNull()
  })
  it('writes the compact forms', () => {
    expect(phaseKitChips({ model: 'claude-haiku-4-5', tools: ['Read', 'Glob', 'Grep', 'Bash', 'WebSearch'], skills: [{ name: 'a', source: 'b' }] })).toEqual([
      { label: 'claude-haiku-4-5', tone: 'neutral' },
      { label: '5 tools', tone: 'neutral' },
      { label: '1 skill', tone: 'accent' },
    ])
    expect(phaseKitChips({ tools: 'default', skills: 'none' })).toEqual([{ label: 'no skills', tone: 'dashed' }])
    expect(phaseKitChips({ tools: 'not-recorded', skills: 'not-recorded' }).map((c) => c.label)).toEqual(['tools not recorded', 'skills not recorded'])
    expect(phaseKitLine(31_800, 0.017, [{ name: 'a', source: 'b' }, { name: 'c', source: 'd' }])).toBe('31.8K tok · $0.0170 · 2 skills')
    expect(ABSENCE_TEXT['not-reported']).toBe('Not reported yet')
  })
})

describe('operations', () => {
  const ops = [
    { id: '1', time: '1:32:36 PM', tool: 'Bash', input: 'python -m py_compile x.py', output: 'python: command not found', status: 'failed' as const },
    { id: '2', time: '1:32:59 PM', tool: 'Edit', input: '/workspace/deliverable.md', status: 'ok' as const, duration: '1s' },
    { id: '3', time: '1:33:08 PM', tool: 'Capture', input: 'Session captured', status: 'quiet' as const },
  ]
  it('picks glyphs and status text', () => {
    expect(toolGlyph('Bash')).toBe(GLYPH.terminal)
    expect(toolGlyph('MultiEdit')).toBe(GLYPH.edit)
    expect(toolGlyph('WebFetch')).toBe(GLYPH.globe)
    expect(toolGlyph('mcp__thing')).toBe(GLYPH.tool)
    expect(operationStatusText(ops[0]!)).toBe('failed · 0s')
    expect(operationStatusText(ops[1]!)).toBe('ok · 1s')
    expect(operationStatusText(ops[2]!)).toBe('')
  })
  it('copies all as plain text', () => {
    expect(operationsToText(ops.slice(0, 2))).toBe(
      '1:32:36 PM  Bash  python -m py_compile x.py\npython: command not found\n\n1:32:59 PM  Edit  /workspace/deliverable.md',
    )
  })
  it('folds long outputs', () => {
    expect(foldOutput('a\nb', 8)).toEqual({ preview: 'a\nb', hidden: 0 })
    expect(foldOutput('1\n2\n3\n4', 2)).toEqual({ preview: '1\n2', hidden: 2 })
  })
})

describe('provenance', () => {
  it('summarises counts with plurals', () => {
    expect(provenanceSummary({ platformSessions: 3, nativeTranscripts: 0, invocations: 0, gaps: 1 })).toBe(
      '3 platform sessions · 0 native transcripts · 0 invocations · 1 gap',
    )
    expect(provenanceSummary({ platformSessions: 1 })).toBe('1 platform session')
  })
})

describe('rule sentence', () => {
  const clauses = buildRuleClauses({
    event: 'check_run.completed',
    repository: 'syntropic137/syntropic137',
    conditions: [
      { field: 'check_run.conclusion', operator: 'eq', value: 'failure' },
      { field: 'check_run.pull_requests', operator: 'not_empty' },
    ],
    workflowName: 'Self-Heal PR',
    workflowHref: '/workflows/self-heal-pr',
    inputs: { repository: 'repository.full_name', pr_number: 'check_run.pull_requests[0].number' },
    caps: [{ value: '3', label: 'max attempts' }],
    log: "Hasn't fired yet",
    logDetail: 'Each firing will list the event, the execution it started and the outcome.',
  })
  it('reads When, If, Then, Cap, Log', () => {
    expect(clauses.map((c) => c.key)).toEqual(['when', 'if', 'then', 'cap', 'log'])
    expect(clauses[1]!.lines[0]).toEqual([{ code: 'check_run.conclusion' }, ' equals', ' ', { code: 'failure', tone: 'danger' }])
    expect(clauses[1]!.lines[1]![0]).toEqual({ muted: 'and' })
    expect(clauses[2]!.mapping).toHaveLength(2)
    expect(ruleText(clauses.slice(0, 3))).toBe(
      'When: GitHub sends check_run.completed on syntropic137/syntropic137. If: check_run.conclusion equals failure and check_run.pull_requests is not empty. Then: Run Self-Heal PR with these inputs',
    )
  })
  it('leaves out empty clauses and names unknown operators', () => {
    const c = buildRuleClauses({ event: 'push', workflowName: 'W' })
    expect(c.map((x) => x.key)).toEqual(['when', 'then'])
    expect(operatorWords('greater_than')).toEqual({ words: 'greater than', takesValue: true })
  })
})

describe('agent prompt', () => {
  it('reproduces the Workflow board prompt', () => {
    expect(
      buildAgentPrompt({
        workflowName: 'Research Workflow',
        workflowId: 'research-workflow-v2',
        inputs: [
          { name: 'task', required: true, description: 'fills $ARGUMENTS in the phase prompts.', placeholder: '<what to research>' },
          { name: 'topic', required: false, placeholder: '<short label>' },
        ],
        phases: ['Discovery Phase', 'Deep Dive Analysis', 'Synthesis & Documentation'],
      }),
    ).toBe(
      [
        'Run the Syn137 workflow "Research Workflow" (research-workflow-v2).',
        '',
        'Start it with the Syn137 CLI:',
        '  syn workflow run research-workflow-v2 --task "<what to research>"',
        '',
        'Inputs',
        '- task (required): fills $ARGUMENTS in the phase prompts.',
        '- topic (optional): add --input topic=<short label>.',
        '',
        'It runs 3 phases in order: Discovery Phase, Deep Dive Analysis, Synthesis & Documentation.',
        'When it finishes, report the execution ID and link the artifact each phase produced.',
      ].join('\n'),
    )
  })
  it('passes other required inputs on the command line', () => {
    const p = buildAgentPrompt({ workflowName: 'W', workflowId: 'w', inputs: [{ name: 'pr', required: true }] })
    expect(p).toContain('syn workflow run w --input pr=<value>')
    expect(p.endsWith('report the execution ID.')).toBe(true)
  })
})
