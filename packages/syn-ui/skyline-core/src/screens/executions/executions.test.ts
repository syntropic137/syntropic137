import { describe, expect, it } from 'vitest'
import { usageModel } from '../../patterns/usage'
import {
  runDurationMs,
  runDurationText,
  ageGroupTitle,
  calendarDaysAgo,
  evalBadge,
  parseEvalFilter,
  phaseProgressText,
  isExecutionEvent,
  canCancel,
  costRowsByModel,
  costRowsByPhase,
  executionsLede,
  executionsLedeShort,
  groupByAge,
  listSummary,
  outcomeTotals,
  parseTimeWindow,
  DEFAULT_LIST_WINDOW,
  timeWindowParam,
  type PhaseLike,
  phaseKit,
  phaseMeta,
  phaseModelChip,
  phaseTokenSplit,
  provenanceFor,
  phaseSkillUseText,
  skillUseNote,
  SKILL_USE_NOT_REPORTED,
  runIdentityText,
  shortPhaseName,
  shortRevision,
  timeWindowStart,
  timelineCaption,
  usageNote,
} from './index'

const NOW = Date.parse('2026-10-08T12:00:00Z')
const DAY = 86_400_000

const phase = (o: Partial<PhaseLike> = {}): PhaseLike => ({
  name: 'Discovery Phase',
  status: 'completed',
  input_tokens: 25,
  output_tokens: 1801,
  cache_creation_tokens: 31442,
  cache_read_tokens: 60160,
  duration_seconds: 24.3,
  cost_usd: 0.0557,
  model: null,
  requested_model: 'haiku',
  model_display: 'unknown (requested: haiku)',
  start_pins_status: 'not_recorded',
  pinned_at_start: null,
  ...o,
})

describe('list', () => {
  it('parses and bounds time windows', () => {
    expect(parseTimeWindow('7d')).toBe('7d')
    expect(parseTimeWindow('nope')).toBe('all')
    expect(timeWindowStart('all', NOW)).toBeUndefined()
    expect(timeWindowStart('1h', NOW)).toBe('2026-10-08T11:00:00.000Z')
  })

  it('defaults the lists to 24h; All stays selectable as ?window=all', () => {
    expect(DEFAULT_LIST_WINDOW).toBe('24h')
    expect(parseTimeWindow(null, DEFAULT_LIST_WINDOW)).toBe('24h')
    expect(parseTimeWindow('all', DEFAULT_LIST_WINDOW)).toBe('all')
    expect(parseTimeWindow('bogus', DEFAULT_LIST_WINDOW)).toBe('24h')
    expect(timeWindowParam('24h', DEFAULT_LIST_WINDOW)).toBeNull()
    expect(timeWindowParam('all', DEFAULT_LIST_WINDOW)).toBe('all')
    expect(timeWindowParam('7d', DEFAULT_LIST_WINDOW)).toBe('7d')
    expect(timeWindowParam('all')).toBeNull()
  })

  it('names age groups like the board', () => {
    // Local noon, so the cases hold in any time zone.
    const noon = new Date(2026, 9, 8, 12).getTime()
    expect(ageGroupTitle(new Date(noon - 3_600_000).toISOString(), noon)).toBe('Today')
    expect(ageGroupTitle(noon - 1.5 * DAY, noon)).toBe('Yesterday')
    expect(ageGroupTitle(noon - 8 * DAY, noon)).toBe('Last week')
    expect(ageGroupTitle(noon - 43 * DAY, noon)).toBe('6 weeks ago')
    expect(ageGroupTitle(null, noon)).toBe('Undated')
  })

  it('groups by local calendar day, not a rolling 24h (parity 2026-10-09: 38 rows all under Today)', () => {
    const now = new Date(2026, 9, 9, 13, 0).getTime()
    expect(ageGroupTitle(new Date(2026, 9, 9, 0, 5).getTime(), now)).toBe('Today')
    // Inside the 24h window but before today's local midnight.
    expect(ageGroupTitle(new Date(2026, 9, 8, 23, 59).getTime(), now)).toBe('Yesterday')
    expect(ageGroupTitle(new Date(2026, 9, 8, 14, 0).getTime(), now)).toBe('Yesterday')
    expect(ageGroupTitle(new Date(2026, 9, 7, 23, 0).getTime(), now)).toBe('This week')
    expect(calendarDaysAgo(new Date(2026, 9, 9, 0, 1).getTime(), new Date(2026, 9, 9, 23, 59).getTime())).toBe(0)
    const rows = [new Date(2026, 9, 9, 9).getTime(), new Date(2026, 9, 8, 22).getTime(), new Date(2026, 9, 8, 19).getTime()].map((t) => ({ t: new Date(t).toISOString() }))
    expect(groupByAge(rows, (r) => r.t, now).map((g) => [g.title, g.count])).toEqual([
      ['Today', '1 run'],
      ['Yesterday', '2 runs'],
    ])
  })

  it('groups consecutive rows and counts them', () => {
    const rows = [NOW - 8 * DAY, NOW - 9 * DAY, NOW - 43 * DAY].map((t) => ({ t: new Date(t).toISOString() }))
    const groups = groupByAge(rows, (r) => r.t, NOW)
    expect(groups.map((g) => [g.title, g.count])).toEqual([
      ['Last week', '2 runs'],
      ['6 weeks ago', '1 run'],
    ])
  })

  it('folds status counts and writes the lede', () => {
    const t = outcomeTotals({ completed: 50, failed: 23, cancelled: 2 })
    expect(t).toMatchObject({ total: 75, completed: 50, failed: 23, cancelled: 2, running: 0 })
    expect(executionsLede(t)).toBe('Every workflow run, newest first. 75 so far, none running.')
    expect(executionsLedeShort(t)).toBe('75 runs, none running now')
    expect(executionsLede({ total: 3, running: 1 })).toContain('1 running')
  })

  it('summarises a page', () => {
    expect(listSummary(1, 50, 19, 75)).toBe('Showing 1–19 of 75 executions')
    expect(listSummary(2, 50, 25, 75, 'failed')).toBe('Showing 51–75 of 75 failed executions')
    expect(listSummary(1, 50, 0, 0)).toBe('No executions')
  })
})

describe('detail', () => {
  it('splits tokens and writes phase meta', () => {
    expect(phaseTokenSplit(phase())).toBe('60.2K read · 31.4K write · 1.8K out · 25 in')
    const m = phaseMeta(phase())
    expect(m.metaShort).toBe('24.3s')
    expect(m.meta).toBe('24.3s · 93.4K tokens · $0.0557')
    expect(m.phone).toBe('24.3s · 93.4K tokens')
  })

  it('sums the timeline', () => {
    const ps = [phase({ duration_seconds: 24.3 }), phase({ duration_seconds: 118.9 }), phase({ duration_seconds: 80.6 })]
    expect(timelineCaption(ps)).toBe('223.8s inside phases.')
    expect(timelineCaption([phase({ duration_seconds: null })])).toBeNull()
  })

  it('chips the model', () => {
    expect(phaseModelChip(phase())).toBe('Claude · haiku requested')
    expect(phaseModelChip(phase({ model: 'claude-haiku-4-5' }))).toBe('claude-haiku-4-5')
    // Never a model that was not observed (feedback 58868cd8).
    expect(phaseModelChip(phase({ requested_model: null, model_display: 'unknown' }))).toBe('model not reported')
  })

  it('reads the kit from start pins', () => {
    expect(phaseKit(phase())).toEqual({ tools: 'not-recorded', skills: 'not-recorded' })
    const kit = phaseKit(
      phase({
        start_pins_status: 'recorded',
        pinned_at_start: { provider: 'claude', allowed_tools: [], skills: [{ name: 'scribe', version: 'main', resolved_sha: 'abc', source_url: 'x/y' }] },
      }),
    )
    expect(kit.tools).toBe('default')
    expect(kit.skills).toEqual([{ name: 'scribe', source: 'x/y', ref: 'main', digest: 'abc' }])
  })

  it('shortens phase names for cost rows', () => {
    expect(shortPhaseName('Discovery Phase')).toBe('Discovery')
    expect(shortPhaseName('Deep Dive Analysis')).toBe('Deep Dive')
    expect(shortPhaseName('Synthesis & Documentation')).toBe('Synthesis')
    expect(costRowsByPhase([phase()])).toEqual([{ label: '01 Discovery', value: 0.0557, tone: 'accent' }])
    // The live API sends Decimal as a string; the meter needs a number for its bars and shares.
    expect(costRowsByPhase([phase({ cost_usd: '0.3480798' })])[0]!.value).toBe(0.3480798)
  })

  it('sums cost by model across phases (exec-0f9f25d20055 live, 2026-10-09: opus $4.57, sol $3.84)', () => {
    const phases = [
      phase({ cost_by_model: { 'claude-opus-5-5': '0.3480798' } }),
      phase({ cost_by_model: { 'gpt-6.1-sol': '2.7898268' } }),
      phase({ cost_by_model: { 'claude-opus-5-5': '3.5115558' } }),
      phase({ cost_by_model: { 'gpt-6.1-sol': '1.0506504' } }),
      phase({ cost_by_model: { 'claude-opus-5-5': '0.7092122', 'unattributed-model': '0.01' } }),
      phase({ cost_by_model: {} }),
    ]
    const rows = costRowsByModel(phases)
    expect(rows.map((r) => r.label)).toEqual(['claude-opus-5-5', 'gpt-6.1-sol', 'unknown model'])
    expect(rows[0]!.value).toBeCloseTo(4.5688478, 7)
    expect(rows[1]!.value).toBeCloseTo(3.8404772, 7)
    const m = usageModel({ tokens: { input: 1, output: 1, cacheRead: 1, cacheWrite: 1 }, costBy: 'phase', costRows: [], modelRows: rows })
    expect(m.modelRows.map((r) => [r.display, r.percent])).toEqual([['$4.57', '54%'], ['$3.84', '46%'], ['$0.0100', '0%']])
    expect(costRowsByModel([phase()])).toEqual([])
  })

  it('notes an unknown model', () => {
    expect(usageNote([phase(), phase(), phase()])).toBe('Model unknown: all three phases requested haiku, and the cost is not attributed to a model.')
    expect(usageNote([phase({ model: 'claude-haiku-4-5' })])).toBeUndefined()
  })

  it('builds provenance with and without an inventory', () => {
    const bare = provenanceFor([phase(), phase({ status: 'pending' })], null)
    expect(bare.counts.platformSessions).toBe(1)
    expect(bare.actionLabel).toBeNull()
    const full = provenanceFor([phase()], {
      reconstruction_status: 'current',
      later_evidence_pending: false,
      summary: {
        complete: false,
        coverage_state: 'unsupported',
        coverage_display: 'Missing host registration affects all 3.',
        revision: 'f82315509573aaaaaaaaaaaaaaaab742d4d5',
        platform_sessions: 3,
        native_transcripts: 0,
        invocations: 0,
        gaps: 1,
        remote_replication: 'disabled',
      },
    })
    expect(full.warning?.lead).toBe("Coverage can't be proven for this harness.")
    expect(full.facts).toEqual(['revision f82315509573…b742d4d5', 'reconstruction current', 'remote replication off'])
    expect(shortRevision('short')).toBe('short')
  })

  it('copies identity and gates cancel', () => {
    const text = runIdentityText({ workflow_execution_id: 'exec-1', workflow_id: 'wf', workflow_name: 'Research', status: 'completed', started_at: null, repos: ['a/b'] })
    expect(text).toBe('execution: exec-1\nworkflow: Research (wf)\nstatus: completed\nrepos: a/b')
    expect(canCancel('running')).toBe(true)
    expect(canCancel('queued')).toBe(true)
    expect(canCancel('completed')).toBe(false)
  })
})

describe('isExecutionEvent', () => {
  it("matches the API's real event_type names, not snake_case guesses", () => {
    for (const t of ['WorkflowExecutionStarted', 'WorkflowCompleted', 'WorkflowFailed', 'PhaseStarted', 'PhaseCompleted']) expect(isExecutionEvent(t)).toBe(true)
    for (const t of ['SessionStarted', 'git_commit', 'connected']) expect(isExecutionEvent(t)).toBe(false)
  })
})

describe('eval marker and progress text', () => {
  it('marks a run that belongs to an eval (feedback 4df2bfc9)', () => {
    expect(evalBadge(null)).toBeNull()
    expect(evalBadge(undefined)).toBeNull()
    expect(evalBadge({ eval_id: 'eval-1', eval_name: 'verifier-seed: x', association_kind: 'launched', verdict: 'PASS', score: 1 })).toEqual({
      label: 'Eval',
      title: 'Eval run of verifier-seed: x (launched) · verdict PASS',
      href: '/evals/eval-1',
    })
    expect(evalBadge({ eval_id: 'eval-2' })?.title).toBe('Eval run of eval-2 · not scored yet')
    expect(parseEvalFilter('1')).toBe(true)
    expect(parseEvalFilter(null)).toBe(false)
  })
  it('writes header progress from the same plan the phase list draws (feedback 9a95d8f7)', () => {
    expect(phaseProgressText('phase 2 of up to 8', 1, 8)).toBe('phase 2 of up to 8')
    expect(phaseProgressText('3 of up to 10, failed', 3, 10)).toBe('phases 3 of up to 10, failed')
    expect(phaseProgressText(null, 1, 3)).toBe('1 of 3 phases')
    expect(phaseProgressText(undefined, 0, 1)).toBe('0 of 1 phase')
  })
})

describe('runDurationMs / runDurationText (feedback 5ed77fc5: durations froze until a refresh)', () => {
  const started = Date.parse('2026-10-10T00:00:00Z')
  it('a running run is measured from its start to now, so a ticking now moves it', () => {
    const r = { status: 'running', started_at: '2026-10-10T00:00:00Z', duration_seconds: 10, duration_display: '10s' }
    expect(runDurationMs(r, started + 50_000)).toBe(50_000)
    expect(runDurationMs(r, started + 51_000)).toBe(51_000)
    expect(runDurationText(r, started + 50_000)).not.toBe('10s')
    expect(runDurationText(r, started + 50_000)).toBe(runDurationText(r, started + 50_000))
  })
  it('a finished run keeps the server duration and its display text', () => {
    const r = { status: 'completed', started_at: '2026-10-10T00:00:00Z', duration_seconds: 10, duration_display: '10s' }
    expect(runDurationMs(r, started + 50_000)).toBe(10_000)
    expect(runDurationText(r, started + 50_000)).toBe('10s')
  })
  it('a running run with no start falls back to the server duration, then to a dash', () => {
    expect(runDurationMs({ status: 'running', started_at: null, duration_seconds: 7 }, started)).toBe(7_000)
    expect(runDurationText({ status: 'running', started_at: null, duration_seconds: null }, started)).toBe('\u2014')
  })
  it('a start in the future is not a negative duration', () => {
    expect(runDurationMs({ status: 'running', started_at: '2026-10-10T00:00:00Z', duration_seconds: null }, started - 1000)).toBeNull()
  })
})

describe('skill use (parity-2: the API reports it, so the screen must)', () => {
  // exec-64e1d7e33b6a on the VPS, 2026-10-10: skill_use as the API returned it.
  const use = {
    declared: ['principles-and-patterns', 'architecture', 'purpose-and-scope', 'types', 'error-handling', 'testing', 'software-complexity', 'security', 'documentation'],
    invoked: [
      { name: 'architecture', count: 1 },
      { name: 'claude-api', count: 1 },
      { name: 'documentation', count: 1 },
      { name: 'error-handling', count: 1 },
      { name: 'principles-and-patterns', count: 1 },
      { name: 'purpose-and-scope', count: 2 },
      { name: 'types', count: 1 },
    ],
    never_invoked: [],
    not_known: ['testing', 'software-complexity', 'security'],
    summary_display: '9 skills declared · 6 invoked · 3 use unknown · 1 undeclared invoked',
  }
  const pinned = phase({ start_pins_status: 'recorded', pinned_at_start: { provider: 'claude', skills: [] } })

  it('renders the API summary and names instead of "not reported"', () => {
    const p = provenanceFor([pinned], null, use)
    expect(p.note).toBe(
      'Skills: 9 skills declared · 6 invoked · 3 use unknown · 1 undeclared invoked. ' +
        'Invoked: architecture, claude-api (undeclared), documentation, error-handling, principles-and-patterns, purpose-and-scope (2 calls), types. ' +
        'Use unknown: testing, software-complexity, security.',
    )
    expect(p.note).not.toContain('not reported')
    expect(skillUseNote({ ...use, invoked: [], not_known: [], never_invoked: ['testing'] })).toContain('Never invoked: testing.')
  })

  it('says it is not reported only when the server sent no skill use', () => {
    expect(provenanceFor([pinned], null).note).toBe(SKILL_USE_NOT_REPORTED)
    expect(provenanceFor([phase()], null, null).note).toContain(SKILL_USE_NOT_REPORTED)
    expect(provenanceFor([phase()], null, use).note).toMatch(/^This run started before start config was pinned.*Skills: 9 skills declared/)
  })

  it("shows a phase's own summary verbatim, and nothing when it has no skills", () => {
    expect(phaseSkillUseText(phase({ skill_use: { status: 'observed', declared: ['a', 'b', 'c'], invoked: [{ name: 'a', count: 1 }], summary_display: '1 of 3 declared skills invoked' } }))).toBe('1 of 3 declared skills invoked')
    expect(phaseSkillUseText(phase({ skill_use: { status: 'unavailable', declared: [], invoked: [], summary_display: 'skill use unavailable: no record for this run' } }))).toBeNull()
    expect(phaseSkillUseText(phase())).toBeNull()
  })
})
